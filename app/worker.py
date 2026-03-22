import asyncio
from app.services.kafka import KafkaService, consume_and_save_bids

async def main():
    print("👷 Python Kafka Worker Started! Waiting for bids...")
    try:
        await consume_and_save_bids()
    except asyncio.CancelledError:
        print("🛑 Worker shutting down...")
    finally:
        await KafkaService.close()
        print("✅ Kafka connection closed.")

if __name__ == "__main__":
    asyncio.run(main()) 