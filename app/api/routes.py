from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis
from app.core.config import settings
from app.db.session import get_db
from app.db.models import User, Auction, Bid
from app.schemas.auction import UserCreate, AuctionCreate, AuctionResponse, BidRequest
from app.services.lock import RedisDistributedLock  # Redis-based distributed lock
from app.services.websocket import manager
from app.services.kafka import KafkaService
from fastapi import WebSocket, WebSocketDisconnect

router = APIRouter()
redis_client = redis.from_url(settings.REDIS_URL)

# 1. Create a test user
@router.post("/users")
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    new_user = User(username=user.username)
    db.add(new_user)
    try:
        await db.commit()
        await db.refresh(new_user)
        return {"id": new_user.id, "username": new_user.username}
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User may already exist.")

# 2. Create a new auction item (e.g., iPhone 15)
@router.post("/auctions", response_model=AuctionResponse)
async def create_auction(item: AuctionCreate, db: AsyncSession = Depends(get_db)):
    new_item = Auction(item_name=item.item_name, current_price=item.current_price)
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)
    return new_item

# 3. Get all auction items (for verification)
@router.get("/auctions")
async def get_auctions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Auction))
    auctions = result.scalars().all()
    return auctions

# 4. Place a bid on an auction item
@router.post("/bid")
async def place_bid(
    bid_req: BidRequest,
    db: AsyncSession = Depends(get_db),
):
    # Base key for this auction in Redis (e.g., auction:1)
    auction_key = f"auction:{bid_req.auction_id}"

    # 1. Try to acquire a distributed lock for this auction
    #    This ensures only one request can update this auction at a time
    lock = RedisDistributedLock(redis_client, f"auction:{bid_req.auction_id}")

    async with lock as acquired:
        if not acquired:
            # Could not acquire the lock: another bid is being processed right now
            # Fail fast instead of blocking the client
            raise HTTPException(
                status_code=429,
                detail="Another bid is currently being processed. Please try again shortly.",
            )

        # === 🔒 Critical Section START ===
        # Only one request per auction_id is allowed to execute this block at a time

        # 2. Load current price
        #    First try Redis (in-memory cache, very fast)
        current_price = await redis_client.get(f"{auction_key}:price")

        if current_price:
            # Redis returned a cached price (bytes/str -> int)
            current_price = int(current_price)
        else:
            # Cache miss: fall back to the database
            auction = await db.get(Auction, bid_req.auction_id)
            if not auction:
                # Auction does not exist in the database
                raise HTTPException(
                    status_code=404,
                    detail="Auction not found.",
                )

            # Use DB value as the source of truth for the initial price
            current_price = auction.current_price

            # Cache the current price in Redis so future requests are fast
            await redis_client.set(f"{auction_key}:price", current_price)

        # 3. Validate the new bid amount
        #    Business rule: the bid must be strictly higher than the current price
        if bid_req.amount <= current_price:
            raise HTTPException(
                status_code=400,
                detail=f"Bid amount must be higher than the current price ({current_price}).",
            )

        # 4. Apply the new bid in Redis
        #    I only touch Redis here to keep the critical section as fast as possible.
        #    DB persistence will be handled asynchronously via Kafka.
        await redis_client.set(f"{auction_key}:price", bid_req.amount)

        # === 🔒 Critical Section END ===

    # 5. Publish the bid to Kafka for asynchronous database persistence
    #    The client does not wait for this to complete (lower latency).
    await KafkaService.publish_bid(bid_req.dict())

    # 6. Notify all connected WebSocket clients about the new bid
    message = f"{bid_req.auction_id}:{bid_req.amount}"
    await redis_client.publish("auction_channel", message)

    return {"status": "success", "new_price": bid_req.amount}

@router.websocket("/ws/auction")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)