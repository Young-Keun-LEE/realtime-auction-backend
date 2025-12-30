from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

# 1. User table
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    
    # One user can have many bids
    bids = relationship("Bid", back_populates="user")


# 2. Auction item table
class Auction(Base):
    __tablename__ = "auctions"

    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String, index=True, nullable=False)  # e.g. "iPhone 15 Pro"
    current_price = Column(Integer, default=0, nullable=False)  # current highest bid
    
    # One auction can have many bids
    bids = relationship("Bid", back_populates="auction")


# 3. Bid history table (log)
class Bid(Base):
    __tablename__ = "bids"

    id = Column(Integer, primary_key=True, index=True)
    price = Column(Integer, nullable=False)  # bid amount
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )  # timestamp when the bid was placed
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    auction_id = Column(Integer, ForeignKey("auctions.id"), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="bids")
    auction = relationship("Auction", back_populates="bids")