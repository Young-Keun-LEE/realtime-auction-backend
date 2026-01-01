from locust import HttpUser, task, between
import random

class AuctionUser(HttpUser):
    # The interval between user actions (random between 1 and 3 seconds) -> Adjust to avoid DDOS-like behavior.
    # Uncomment wait_time for extreme stress testing.
    wait_time = between(1, 3)

    @task
    def bid_attack(self):
        # 1. Attempt to place a bid on auction ID 1
        auction_id = 1
        
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

    # Function executed once at the start of the test
    def on_start(self):
        pass