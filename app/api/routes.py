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

BID_LUA_SCRIPT = """
local current_price = redis.call('get', KEYS[1])
if current_price then
    if tonumber(ARGV[1]) <= tonumber(current_price) then
        return 0
    end
    redis.call('set', KEYS[1], ARGV[1])
    return 1
else
    return -1
end
"""

# 4. Place a bid on an auction item
@router.post("/bid")
async def place_bid(
    bid_req: BidRequest,
    db: AsyncSession = Depends(get_db),
):
    # Redis key for storing the current price of the auction
    auction_price_key = f"auction:{bid_req.auction_id}:price"

    # Execute Lua script to atomically check and update the bid price in Redis
    # Returns: -1 (key not found), 0 (bid too low), 1 (bid accepted)
    result = await redis_client.eval(BID_LUA_SCRIPT, 1, auction_price_key, bid_req.amount)

    # Case 1: Redis key doesn't exist yet (first bid or cache miss)
    if result == -1:
        # Fetch auction from database to verify existence and get current price
        auction = await db.get(Auction, bid_req.auction_id)
        if not auction:
            raise HTTPException(status_code=404, detail="Auction not found.")
        
        # Validate bid amount against DB price
        if bid_req.amount <= auction.current_price:
            # Initialize Redis cache with current DB price
            await redis_client.set(auction_price_key, auction.current_price)
            raise HTTPException(
                status_code=400,
                detail=f"Bid amount must be higher than current price ({auction.current_price})."
            )
            # Set the new bid price in Redis cache
            await redis_client.set(auction_price_key, bid_req.amount)
    
    # Case 2: Bid amount is not higher than current cached price
    elif result == 0:
        current_price = await redis_client.get(auction_price_key)
        raise HTTPException(
            status_code=400,
            detail=f"Bid amount must be higher than the current price ({current_price.decode() if current_price else 'unknown'}).",
        )
    
    # Publish bid event to Kafka for asynchronous DB persistence
    await KafkaService.publish_bid(bid_req.dict())

    # Publish price update to Redis pub/sub for real-time WebSocket broadcasting
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