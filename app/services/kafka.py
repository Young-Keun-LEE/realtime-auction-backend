import json
import asyncio
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import Auction, Bid
from sqlalchemy import update

class KafkaService:
    """Manages Kafka producer and consumer for the auction system."""
    
    _producer: AIOKafkaProducer = None
    _consumer: AIOKafkaConsumer = None
    
    @classmethod
    async def get_producer(cls) -> AIOKafkaProducer:
        """Get or create the Kafka producer."""
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
        """Publish a bid event to Kafka."""
        producer = await cls.get_producer()
        try:
            await producer.send_and_wait(
                settings.KAFKA_BID_TOPIC,
                value=bid_data
            )
            print(f"📤 [Kafka Published] Bid: {bid_data}")
        except Exception as e:
            print(f"❌ [Kafka Error] Failed to publish bid: {e}")
    
    @classmethod
    async def get_consumer(cls) -> AIOKafkaConsumer:
        """Get the Kafka consumer for bid events."""
        if cls._consumer is None:
            cls._consumer = AIOKafkaConsumer(
                settings.KAFKA_BID_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="auction-processor",
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                auto_offset_reset='earliest'
            )
            await cls._consumer.start()
            print("✅ Kafka Consumer Started")
        return cls._consumer
    
    @classmethod
    async def close(cls) -> None:
        """Close both producer and consumer."""
        if cls._producer:
            await cls._producer.stop()
            print("🛑 Kafka Producer Stopped")
        if cls._consumer:
            await cls._consumer.stop()
            print("🛑 Kafka Consumer Stopped")


async def consume_and_save_bids():
    """
    Consumer that listens to Kafka bids topic and saves them to the database.
    This runs as a background task in the application lifecycle.
    """
    consumer = await KafkaService.get_consumer()
    
    try:
        async for message in consumer:
            bid_data = message.value
            print(f"📥 [Kafka Consumed] Bid: {bid_data}")
            
            # Save the bid to the database
            await save_bid_to_db(bid_data)
    except asyncio.CancelledError:
        print("🛑 Bid consumer cancelled")
    except Exception as e:
        print(f"❌ [Consumer Error] {e}")


async def save_bid_to_db(bid_data: dict):
    """
    Persist the bid to the database.
    
    This function is called by the Kafka consumer to save bids
    that were published from the place_bid endpoint.
    """
    async with AsyncSessionLocal() as session:
        try:
            # 1) Insert a new Bid row with idempotency check
            stmt = Insert(Bid).values(
                bid_id=bid_data["bid_id"],
                price=bid_data["amount"],
                user_id=bid_data["user_id"],
                auction_id=bid_data["auction_id"]
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=['bid_id'])
            result = await session.execute(stmt)

            if result.rowcount == 0:
                print(f"⚠️ [Idempotent] Already processed bid ignored: {bid_data['bid_id']}")
                return

            # 2) Update the Auction's current_price
            stmt = (
                update(Auction)
                .where(Auction.id == bid_data["auction_id"])
                .values(current_price=bid_data["amount"])
            )
            await session.execute(stmt)

            # 3) Commit the transaction
            await session.commit()
            print(
                f"✅ [DB Saved] Auction {bid_data['auction_id']} updated to {bid_data['amount']}"
            )

        except Exception as e:
            # If anything fails, roll back this transaction
            await session.rollback()
            print(f"❌ [DB Error] Failed to save bid: {e}")
