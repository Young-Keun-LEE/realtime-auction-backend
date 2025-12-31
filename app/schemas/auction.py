from pydantic import BaseModel

# 1. Data received when creating a new auction
class AuctionCreate(BaseModel):
    item_name: str
    current_price: int = 0

# 2. Data received when creating a new user
class UserCreate(BaseModel):
    username: str

# 3. Data shape returned in responses
class AuctionResponse(BaseModel):
    id: int
    item_name: str
    current_price: int

    class Config:
        # Allow creating this schema directly from ORM objects (SQLAlchemy models)
        from_attributes = True

# 4. Data received when placing a bid
class BidRequest(BaseModel):
    user_id: int
    auction_id: int
    amount: int