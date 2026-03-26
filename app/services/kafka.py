# app/services/kafka.py
import json
import asyncio
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import update
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import Auction, Bid

class KafkaService:
    """Manages Kafka producer and consumer for the auction system."""
    
    _producer: AIOKafkaProducer = None
    _consumer: AIOKafkaConsumer = None
    
    @classmethod
    async def get_producer(cls) -> AIOKafkaProducer:
        if cls._producer is None:
            cls._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            await cls._producer.start()
            print("✅ Kafka Producer Started")
        return cls._producer
    
    @classmethod
    async def publish_bid(cls, bid_data: dict) -> None:
        producer = await cls.get_producer()
        try:
            await producer.send_and_wait(
                settings.KAFKA_BID_TOPIC,
                value=bid_data
            )
        except Exception as e:
            print(f"❌ [Kafka Error] Failed to publish bid: {e}")
    
    @classmethod
    async def get_consumer(cls) -> AIOKafkaConsumer:
        if cls._consumer is None:
            cls._consumer = AIOKafkaConsumer(
                settings.KAFKA_BID_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="auction-processor",
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset='earliest',
                enable_auto_commit=False 
            )
            await cls._consumer.start()
            print("✅ Kafka Consumer Started")
        return cls._consumer
    
    @classmethod
    async def close(cls) -> None:
        if cls._producer:
            await cls._producer.stop()
        if cls._consumer:
            await cls._consumer.stop()


async def consume_and_save_bids():
    """
    Consumer that listens to Kafka bids topic and saves them to the database in BATCHES.
    """
    consumer = await KafkaService.get_consumer()
    
    while True:
        try:
            # 1: Wait up to 1 second (1000ms), or fetch once when 1000 messages are buffered.
            batch_data = await consumer.getmany(timeout_ms=1000, max_records=1000)

            if not batch_data:
                continue  # Skip if no bids arrived during this 1-second window.

            # Flatten partition-grouped records into a single list.
            bids_to_process = []
            for tp, messages in batch_data.items():
                for message in messages:
                    bids_to_process.append(message.value)

            if bids_to_process:
                print(f"📦 [Batch Processing] Received {len(bids_to_process)} bids in this window.")
                await save_bids_batch_to_db(bids_to_process)
                await consumer.commit()  # Manual commit: commit offsets only after successful batch processing.
        except asyncio.CancelledError:
            print("🛑 Bid consumer cancelled")
            raise
        except Exception as e:
            print(f"❌ [Consumer Error] {e}")
            continue  # Keep consuming subsequent messages even if an error occurs.


async def save_bids_batch_to_db(bids: list[dict]):
    """
    Persist a batch of bids to the database efficiently.
    """
    async with AsyncSessionLocal() as session:
        try:
            # 1) Prepare bulk insert.
            insert_values = [
                {
                    "bid_id": b["bid_id"], # UUID used for idempotency protection.
                    "user_id": b["user_id"],
                    "auction_id": b["auction_id"],
                    "price": b["amount"]
                }
                for b in bids
            ]

            # 2) Insert up to 1000 bids with a single query (including idempotency safeguard).
            stmt = insert(Bid).values(insert_values)
            stmt = stmt.on_conflict_do_nothing(index_elements=['bid_id'])
            await session.execute(stmt)

            # 3) Compute the highest bid per auction in Python memory.
            auction_max_prices = {}
            for b in bids:
                aid = b["auction_id"]
                amt = b["amount"]
                # Update only when the new amount is higher than the current max.
                if aid not in auction_max_prices or amt > auction_max_prices[aid]:
                    auction_max_prices[aid] = amt

            # 4) Update each auction only with the final max amount.
            # (Even with 1000 bids, only one UPDATE is issued if they belong to one auction.)
            for aid, max_amt in auction_max_prices.items():
                update_stmt = (
                    update(Auction)
                    .where(Auction.id == aid)
                    .values(current_price=max_amt)
                )
                await session.execute(update_stmt)

            # 5) Commit the transaction in one batch.
            await session.commit()
            print(f"✅ [Batch DB Saved] Successfully inserted bids and updated {len(auction_max_prices)} auctions.")

        except Exception as e:
            await session.rollback()
            print(f"❌ [DB Error] Failed to save batch: {e}")
            raise