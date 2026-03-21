from locust import HttpUser, task, between, events
import random
import requests
import time

# Global data shared by all users
auction_ids = []
auction_prices = {}  # Track current prices per auction
last_price_update = {}  # Track when prices were last fetched

# This runs ONCE at the very start of the test (before any users spawn)
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global auction_ids, auction_prices
    
    print("🔄 Creating test data (users & auctions)...")
    
    # Get the host from environment
    host = environment.host or "http://localhost:8001"
    
    try:
        # 1. Create test users first (1-100 for faster setup)
        print("👥 Creating test users...")
        for i in range(1, 101):
            user_payload = {
                "username": f"test-user-{i}"
            }
            resp = requests.post(f"{host}/api/v1/users", json=user_payload)
            # Ignore if user already exists
        
        print(f"✅ Created/verified 100 test users")
        
        # 2. Create test auctions with varied starting prices
        print("🎁 Creating test auctions...")
        for i in range(1, 6):  # Create 5 auctions (more manageable)
            start_price = random.randint(1000, 5000)
            payload = {
                "item_name": f"test-auction-item-{i}",
                "current_price": start_price
            }
            resp = requests.post(f"{host}/api/v1/auctions", json=payload)
            if resp.status_code == 200:
                auction_data = resp.json()
                auction_id = auction_data["id"]
                auction_ids.append(auction_id)
                # Initialize price tracking
                auction_prices[auction_id] = start_price
                last_price_update[auction_id] = time.time()
        
        print(f"✅ Created {len(auction_ids)} auctions: {auction_ids}")
        print(f"📊 Initial prices: {auction_prices}")
    except Exception as e:
        print(f"❌ Error creating test data: {e}")


class AuctionUser(HttpUser):
    # Simulate different user profiles
    # Some users bid frequently, others bid occasionally
    wait_time = between(0.5, 5)  # More realistic wait interval (0.5-5 seconds)
    
    def on_start(self):
        """Called when each simulated user starts."""
        # Choose bidding behavior per user
        self.user_type = random.choice(["aggressive", "moderate", "conservative"])
        self.favorite_auction = None  # Specific auction this user is interested in
        
        if random.random() < 0.7:  # 70% of users focus on one specific auction
            self.favorite_auction = random.choice(auction_ids)
    
    @task(8)  # This task runs 8 times more often than others
    def bid_on_favorite(self):
        """Bid on the user's preferred auction (realistic behavior)."""
        global auction_prices, last_price_update
        
        if not self.favorite_auction:
            return
        
        auction_id = self.favorite_auction
        
        # Price data update (read from cache)
        current_price = auction_prices.get(auction_id, 1000)
        
        # Realistic bid increments by user type
        if self.user_type == "aggressive":
            bid_increment = random.randint(500, 2000)  # Up to +2000
        elif self.user_type == "moderate":
            bid_increment = random.randint(100, 500)   # +100 to +500
        else:  # conservative
            bid_increment = random.randint(50, 200)    # +50 to +200
        
        new_bid = current_price + bid_increment
        
        payload = {
            "user_id": random.randint(1, 100),
            "auction_id": auction_id,
            "amount": new_bid
        }
        
        with self.client.post("/api/v1/bid", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                # Bid accepted -> update tracked price
                auction_prices[auction_id] = new_bid
                last_price_update[auction_id] = time.time()
                response.success()
            elif response.status_code == 400:
                response.success()  # Bid too low or other business-rule error
            elif response.status_code == 429:
                response.success()  # Rate limit (lock waiting)
            else:
                response.failure(f"Server Error: {response.status_code}")
    
    @task(2)  # Runs at 1/4 the frequency of the task above
    def bid_on_random(self):
        """Occasionally bid on random auctions (portfolio diversification)."""
        global auction_prices, last_price_update
        
        if not auction_ids:
            return
        
        # Concentrate more traffic on popular auctions (Pareto principle)
        # 80% of bids target the top 20% of auctions
        if random.random() < 0.8:
            auction_id = auction_ids[0]  # Treat the first auction as the popular one
        else:
            auction_id = random.choice(auction_ids)
        
        current_price = auction_prices.get(auction_id, 1000)
        
        # Conservative bidding on random auctions
        bid_increment = random.randint(50, 300)
        new_bid = current_price + bid_increment
        
        payload = {
            "user_id": random.randint(1, 100),
            "auction_id": auction_id,
            "amount": new_bid
        }
        
        with self.client.post("/api/v1/bid", json=payload, catch_response=True) as response:
            if response.status_code == 200:
                auction_prices[auction_id] = new_bid
                last_price_update[auction_id] = time.time()
                response.success()
            elif response.status_code == 400:
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"Server Error: {response.status_code}")
    
    @task(1)
    def get_auction_status(self):
        """Fetch auction status (users check this occasionally)."""
        with self.client.get("/api/v1/auctions", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to get auctions: {response.status_code}")
        

