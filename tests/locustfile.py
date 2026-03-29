from locust import HttpUser, task, between, events
import random
import requests
import time
import json
import os

# Global data shared by all users
auction_ids = []
auction_prices = {}      # Track current prices per auction
last_price_update = {}   # Track when prices were last fetched

# Endpoint config
app_api_base = "http://localhost:8000"
bid_api_base = "http://localhost:8080"

# Metrics tracking
metrics = {
    "total_bids": 0,
    "accepted_202": 0,       # Bid accepted (async processing)
    "conflict_409": 0,       # Bid too low (outbid)
    "bad_request_400": 0,    # Malformed JSON
    "unprocessable_422": 0,  # Validation error
    "not_found_404": 0,      # Auction not found
    "unavailable_503": 0,    # Service unavailable
    "server_error_500": 0,   # Internal server error
    "other_errors": 0,
    "retries_after_409": 0,  # Retries after 409 conflict
    "retries_success": 0,    # Successful retries
}


# This runs ONCE at the very start of the test (before any users spawn)
@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global auction_ids, auction_prices, app_api_base, bid_api_base

    print("🔄 Creating test data (users & auctions)...")

    # `--host` is used for the Python app endpoints unless APP_API_BASE is explicitly set.
    app_api_base = os.getenv("APP_API_BASE") or environment.host or "http://localhost:8000"
    # Bid API points to Go service by default; can be overridden by env var.
    bid_api_base = os.getenv("BID_API_BASE", "http://localhost:8080")
    print(f"🌐 App API base: {app_api_base}")
    print(f"🌐 Bid API base: {bid_api_base}")

    try:
        # 1. Create test users (1-100)
        print("👥 Creating test users...")
        for i in range(1, 101):
            user_payload = {"username": f"test-user-{i}"}
            requests.post(f"{app_api_base}/api/v1/users", json=user_payload)
            # Ignore if user already exists

        print("✅ Created/verified 100 test users")

        # 2. Create test auctions with varied starting prices
        print("🎁 Creating test auctions...")
        for i in range(1, 6):  # Create 5 auctions
            start_price = random.randint(1000, 5000)
            payload = {
                "item_name": f"test-auction-item-{i}",
                "current_price": start_price,
            }
            resp = requests.post(f"{app_api_base}/api/v1/auctions", json=payload)
            if resp.status_code == 200:
                auction_data = resp.json()
                auction_id = auction_data["id"]
                auction_ids.append(auction_id)
                auction_prices[auction_id] = start_price
                last_price_update[auction_id] = time.time()

        print(f"✅ Created {len(auction_ids)} auctions: {auction_ids}")
        print(f"📊 Initial prices: {auction_prices}")

    except Exception as e:
        print(f"❌ Error creating test data: {e}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print final metrics when test ends."""
    total = metrics['total_bids']
    accepted = metrics['accepted_202']
    conflicts = metrics['conflict_409']
    
    print("\n" + "=" * 70)
    print("📊 TEST METRICS SUMMARY")
    print("=" * 70)
    print(f"Total bids attempted: {total}")
    
    print(f"\n✅ BUSINESS OUTCOMES (Expected):")
    print(f"   Accepted (202):        {accepted:5d}  ({accepted/max(total,1)*100:5.1f}%)")
    print(f"   Conflicts/Outbid (409):{conflicts:5d}  ({conflicts/max(total,1)*100:5.1f}%)")
    print(f"                          ------")
    print(f"   Processed:             {accepted+conflicts:5d}")
    
    print(f"\n🔄 RETRY HANDLING:")
    print(f"   Conflict retries attempted: {metrics['retries_after_409']}")
    print(f"   Retry success rate:        {metrics['retries_success']}/{metrics['retries_after_409']} ({metrics['retries_success']/max(metrics['retries_after_409'],1)*100:.1f}%)")
    
    print(f"\n❌ ACTUAL SYSTEM FAILURES (Unexpected):")
    total_errors = (metrics['bad_request_400'] + metrics['unprocessable_422'] + 
                    metrics['not_found_404'] + metrics['unavailable_503'] + 
                    metrics['server_error_500'] + metrics['other_errors'])
    print(f"   Malformed JSON (400):     {metrics['bad_request_400']}")
    print(f"   Validation Error (422):   {metrics['unprocessable_422']}")
    print(f"   Auction Not Found (404):  {metrics['not_found_404']}")
    print(f"   Service Unavailable (503):{metrics['unavailable_503']}")
    print(f"   Internal Error (500):     {metrics['server_error_500']}")
    print(f"   Other:                    {metrics['other_errors']}")
    print(f"   ----")
    print(f"   Total System Failures:    {total_errors}")
    
    if total_errors == 0:
        print(f"\n🎉 RELIABILITY: 100% (No system failures)")
    else:
        print(f"\n⚠️  RELIABILITY: {(total-total_errors)/max(total,1)*100:.1f}% ({total_errors} failures)")
    print("=" * 70 + "\n")


class AuctionUser(HttpUser):
    wait_time = between(0.5, 5)

    def on_start(self):
        """Called when each simulated user starts."""
        self.user_type = random.choice(["aggressive", "moderate", "conservative"])

        # 70% of users focus on one specific auction
        self.favorite_auction = (
            random.choice(auction_ids) if auction_ids and random.random() < 0.7 else None
        )

    def _get_bid_increment(self):
        """Return bid increment based on user type."""
        if self.user_type == "aggressive":
            return random.randint(500, 2000)
        elif self.user_type == "moderate":
            return random.randint(100, 500)
        else:  # conservative
            return random.randint(50, 200)

    def _place_bid_with_retry(self, payload, auction_id, retry_count=0, max_retries=2):
        """
        Place bid with optional retry logic for 409 conflicts.
        - retry_count: current retry depth (starts at 0 for the first attempt)
        - max_retries: set to 0 to disable retries (e.g. bid_on_random)
        """
        global auction_prices, last_price_update, metrics

        # ✅ Count total_bids only on the first attempt (not retries)
        if retry_count == 0:
            metrics["total_bids"] += 1

        with self.client.post(f"{bid_api_base}/api/v1/bid", json=payload, catch_response=True) as response:

            if response.status_code == 202:
                # ✅ Bid accepted (async processing)
                # Only update cache if our bid is higher than the known price
                # to avoid overwriting a more recent higher bid from another user
                current_known = auction_prices.get(auction_id, 0)
                if payload["amount"] > current_known:
                    auction_prices[auction_id] = payload["amount"]
                    last_price_update[auction_id] = time.time()

                metrics["accepted_202"] += 1

                # ✅ Track successful retries
                if retry_count > 0:
                    metrics["retries_success"] += 1

                response.success()

            elif response.status_code == 409:
                # ⚠️ Bid too low (outbid) - extract new price and optionally retry
                metrics["conflict_409"] += 1

                try:
                    resp_data = response.json()
                    latest_price = None

                    # Preferred shape: {"current_price": 12500}
                    if "current_price" in resp_data:
                        latest_price = int(resp_data["current_price"])
                    else:
                        # Backward compatibility: parse from detail string
                        detail = resp_data.get("detail", "")
                        if "(" in detail and ")" in detail:
                            current_price_str = detail.split("(")[-1].rstrip(")")
                            latest_price = int(current_price_str)

                    if latest_price is not None:
                        # Update price cache only if it's actually higher
                        if latest_price > auction_prices.get(auction_id, 0):
                            auction_prices[auction_id] = latest_price
                            last_price_update[auction_id] = time.time()

                        # Retry with higher bid if retries are allowed
                        if retry_count < max_retries:
                            metrics["retries_after_409"] += 1
                            retry_payload = payload.copy()
                            retry_payload["amount"] = latest_price + random.randint(50, 200)

                            response.success()

                            self._place_bid_with_retry(
                                retry_payload, auction_id, retry_count + 1, max_retries
                            )
                            return

                except (json.JSONDecodeError, ValueError, IndexError):
                    pass

                response.success()  # Legitimate business outcome, not a test failure

            elif response.status_code == 400:
                metrics["bad_request_400"] += 1
                response.failure(f"Malformed request: {response.text}")

            elif response.status_code == 422:
                metrics["unprocessable_422"] += 1
                response.failure(f"Validation error: {response.text}")

            elif response.status_code == 404:
                metrics["not_found_404"] += 1
                response.failure(f"Auction not found: {response.text}")

            elif response.status_code == 503:
                metrics["unavailable_503"] += 1
                response.failure(f"Service unavailable: {response.text}")

            elif response.status_code == 500:
                metrics["server_error_500"] += 1
                response.failure(f"Server error: {response.text}")

            else:
                metrics["other_errors"] += 1
                response.failure(f"Unexpected status {response.status_code}: {response.text}")

    @task(8)  # Runs 8x more often than get_auction_status
    def bid_on_favorite(self):
        """Bid on the user's preferred auction (realistic behavior)."""
        if not self.favorite_auction or not auction_ids:
            return

        auction_id = self.favorite_auction
        current_price = auction_prices.get(auction_id, 1000)
        new_bid = current_price + self._get_bid_increment()

        payload = {
            "user_id": random.randint(1, 100),
            "auction_id": auction_id,
            "amount": new_bid,
        }

        # Aggressive users retry more, conservative users don't retry
        max_retries = {"aggressive": 3, "moderate": 2, "conservative": 0}.get(self.user_type, 2)
        self._place_bid_with_retry(payload, auction_id, max_retries=max_retries)

    @task(2)  # Runs 2x more often than get_auction_status
    def bid_on_random(self):
        """Occasionally bid on a random auction (portfolio diversification)."""
        if not auction_ids:
            return

        # 80% of bids target the first (most popular) auction — Pareto principle
        auction_id = auction_ids[0] if random.random() < 0.8 else random.choice(auction_ids)
        current_price = auction_prices.get(auction_id, 1000)
        new_bid = current_price + random.randint(50, 300)

        payload = {
            "user_id": random.randint(1, 100),
            "auction_id": auction_id,
            "amount": new_bid,
        }

        # ✅ No retries on random bids — just track and move on
        self._place_bid_with_retry(payload, auction_id, max_retries=0)

    @task(1)
    def get_auction_status(self):
        """Fetch auction status and sync local price cache."""
        with self.client.get(f"{app_api_base}/api/v1/auctions", catch_response=True) as response:
            if response.status_code == 200:
                # ✅ Sync local price cache with actual server prices
                try:
                    auctions = response.json()
                    for auction in auctions:
                        aid = auction.get("id")
                        price = auction.get("current_price")
                        if aid and price is not None:
                            # Always trust the server's price
                            auction_prices[aid] = price
                            last_price_update[aid] = time.time()
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
                response.success()
            else:
                response.failure(f"Failed to get auctions: {response.status_code}")