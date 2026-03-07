from locust import HttpUser, task, between, events
import random
import requests

# Global auction IDs shared by all users
auction_ids = []

# This runs ONCE at the very start of the test (before any users spawn)
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global auction_ids
    
    print("🔄 Creating test auctions once for all users...")
    
    # Get the host from environment
    host = environment.host or "http://localhost:8000"
    
    try:
        for i in range(1, 11):  # Create 10 auctions
            payload = {
                "item_name": f"test-auction-{i}",
                "current_price": 1000
            }
            resp = requests.post(f"{host}/api/v1/auctions", json=payload)
            if resp.status_code == 200:
                auction_data = resp.json()
                auction_ids.append(auction_data["id"])
        
        print(f"✅ Created {len(auction_ids)} auctions: {auction_ids}")
    except Exception as e:
        print(f"❌ Error creating auctions: {e}")







class AuctionUser(HttpUser):
    # The interval between user actions (random between 1 and 3 seconds) -> Adjust to avoid DDOS-like behavior.
    # Uncomment wait_time for extreme stress testing.
    wait_time = between(1, 3)
    
    @task
    def bid_attack(self):
        # Use a random auction from the available pool
        if not auction_ids:
            return  # No auctions available
        
        auction_id = random.choice(auction_ids)
        
        # 2. Send random bid amounts between 10,000 and 100,000
        amount = random.randint(10000, 100000)
        
        payload = {
            "user_id": random.randint(1, 1000), # Random user ID
            "auction_id": auction_id,
            "amount": amount
        }

        # 3. Send POST request
        with self.client.post("/api/v1/bid", json=payload, catch_response=True) as response:
            # 4. Evaluate the result
            if response.status_code == 200:
                response.success() # Bid successful!
            elif response.status_code == 400:
                # "Bid too low" is considered a success since the server is functioning correctly (not an error).
                response.success() 
            elif response.status_code == 429:
                # "Waiting due to lock" is also intended behavior, so consider it a success.
                response.success()
            else:
                # Only treat 500 errors (server crash) as actual failures.
                response.failure(f"Server Error: {response.status_code}")
        

