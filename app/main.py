from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
import redis.asyncio as redis

from app.core.config import settings
from app.db.session import engine
from app.db.models import Base
from app.api.routes import router as api_router
from app.services.websocket import manager
from app.services.kafka import KafkaService, consume_and_save_bids

redis_subscriber = redis.from_url(settings.REDIS_URL)

async def redis_listener():
    """Continuously listen to the Redis Pub/Sub channel and send messages via WebSocket when a message is received."""
    async with redis_subscriber.pubsub() as pubsub:
        await pubsub.subscribe("auction_channel")
        print("🎧 Redis Listener Started: Listening on 'auction_channel'")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"].decode("utf-8")
                print(f"📣 [Broadcasting] New Price: {data}")
                # Send to all WebSocket connections
                await manager.broadcast(data)

# Lifespan: logic that runs when the app starts and stops
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. On server startup: create database tables if they do not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis_task = asyncio.create_task(redis_listener())
    kafka_task = asyncio.create_task(consume_and_save_bids())

    # Application runs and serves requests between yield and the code below
    yield

    # 2. On server shutdown: clean up resources
    redis_task.cancel()
    kafka_task.cancel()
    await KafkaService.close()
    print("🛑 Shutting down...")

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Auction Server is Running! 🚀"}