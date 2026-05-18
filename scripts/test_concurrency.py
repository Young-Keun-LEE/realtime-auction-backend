"""Concurrency test script for the bidding API.

This script issues multiple concurrent bid requests against a single auction to
verify that the Redis-based distributed lock correctly enforces a single winner.
"""

import asyncio
import time
from typing import Tuple

import httpx  # Asynchronous HTTP client (pip install httpx)


APP_BASE_URL = "http://localhost:8000/api/v1"
BID_BASE_URL = "http://localhost:8080/api/v1"
TEST_AUCTION_PRICE = 1000
TEST_BID_AMOUNT = 12000


async def create_test_auction() -> int:
    """Create a fresh auction so the test does not depend on prior DB state."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{APP_BASE_URL}/auctions",
            json={
                "item_name": f"concurrency-test-{int(time.time())}",
                "current_price": TEST_AUCTION_PRICE,
            },
        )
        response.raise_for_status()
        return response.json()["id"]


async def attack_bid(user_id: int, auction_id: int, amount: int) -> Tuple[int, dict]:
    """Send a single bid request for a given user and amount."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BID_BASE_URL}/bid",
            json={
                "user_id": user_id,
                "auction_id": auction_id,
                "amount": amount,
            },
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}
        return response.status_code, payload


async def main() -> None:
    """Run a simple concurrency test against the /bid endpoint."""
    # Step 1: Create a fresh auction
    print("=" * 50)
    print("STEP 1: Creating test auction...")
    auction_id = await create_test_auction()
    print(f"✓ Auction created with ID: {auction_id}")
    print(f"  Initial price: {TEST_AUCTION_PRICE}")
    print()

    # Step 2: Send concurrent bid requests
    print("STEP 2: Sending 30 concurrent bid requests...")
    print(f"  Each bid amount: {TEST_BID_AMOUNT}")
    print()

    tasks = []

    # Create 30 concurrent bid requests with different user IDs
    for i in range(30):
        user_id = i + 1
        tasks.append(
            attack_bid(user_id=user_id, auction_id=auction_id, amount=TEST_BID_AMOUNT)
        )

    start_time = time.time()
    results = await asyncio.gather(*tasks)
    end_time = time.time()

    print("=" * 50)
    print("RESULTS:")
    print("=" * 50)

    success_count = 0
    fail_count = 0

    for i, (status, data) in enumerate(results):
        if status == 202:
            success_count += 1
            print(f"[SUCCESS] User {i+1}: {data}")
        else:
            fail_count += 1
            print(f"[FAILED] User {i+1}: status={status}, detail={data.get('detail')}")

    print()
    print("=" * 50)
    print("SUMMARY:")
    print("=" * 50)
    print(f"Elapsed time: {end_time - start_time:.4f} seconds")
    print(f"Successful bids (202): {success_count} (expected: 1)")
    print(f"Failed bids: {fail_count} (expected: 29)")
    print()

    if success_count == 1:
        print("✓ Concurrency test PASSED: only one winning bid was accepted.")
        print("  ✓ Atomicity is guaranteed - Redis lock works correctly")
    else:
        print("✗ Concurrency test FAILED: multiple bids were accepted concurrently.")
        print("  ✗ Atomicity issue detected - Redis lock failed")


if __name__ == "__main__":
    asyncio.run(main())