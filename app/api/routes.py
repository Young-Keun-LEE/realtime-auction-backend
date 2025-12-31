from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
import redis.asyncio as redis

from app.core.config import settings
from app.db.session import get_db, AsyncSessionLocal
from app.db.models import User, Auction, Bid
from app.schemas.auction import UserCreate, AuctionCreate, AuctionResponse, BidRequest
from app.services.lock import RedisDistributedLock  # Redis-based distributed lock

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
    background_tasks: BackgroundTasks,  # Used to schedule async work after response
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
        #    DB persistence will be handled asynchronously after the response.
        await redis_client.set(f"{auction_key}:price", bid_req.amount)

        # === 🔒 Critical Section END ===

    # 5. Persist the bid to the database asynchronously
    #    The client does not wait for this to complete (lower latency).
    background_tasks.add_task(save_bid_to_db, bid_req.dict())

    return {"status": "success", "new_price": bid_req.amount}


async def save_bid_to_db(bid_data: dict):
    """
    Persist the bid to the database in the background.

    IMPORTANT:
    - BackgroundTasks run outside the original request lifecycle.
    - I must NOT reuse the request-scoped AsyncSession here.
    - Instead, we create a new AsyncSession for this background job.
    """
    async with AsyncSessionLocal() as session:
        try:
            # 1) Insert a new Bid row
            new_bid = Bid(
                user_id=bid_data["user_id"],
                auction_id=bid_data["auction_id"],
                price=bid_data["amount"],
            )
            session.add(new_bid)

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