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

# 1. Create a user
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

# 4. Notice new price updates via WebSocket (for real-time updates)
@router.websocket("/ws/auction/{auction_id}")
async def websocket_endpoint(websocket: WebSocket, auction_id: str):
    await manager.connect(websocket, auction_id)
    try:
        while True:
            data = await websocket.receive_text()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, auction_id)