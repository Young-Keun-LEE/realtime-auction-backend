"""Concurrency test script for the bidding API.

This script issues multiple concurrent bid requests against a single auction to
verify that the Redis-based distributed lock correctly enforces a single winner.
"""

import asyncio
import time
from typing import Tuple

import httpx  # Asynchronous HTTP client (pip install httpx)


BASE_URL = "http://localhost:8000/api/v1"


async def attack_bid(user_id: int, amount: int) -> Tuple[int, dict]:
    """Send a single bid request for a given user and amount."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/bid",
            json={
                "user_id": user_id,
                "auction_id": 1,  # Target auction ID
                "amount": amount,
            },
        )
        return response.status_code, response.json()


async def main() -> None:
    """Run a simple concurrency test against the /bid endpoint."""
    print("Starting concurrency test: 30 clients bidding 12,000 in parallel")

    tasks = []
    target_price = 12000

    # For simplicity, use the same user ID for all requests.
    for _ in range(30):
        tasks.append(attack_bid(user_id=1, amount=target_price))

    start_time = time.time()
    results = await asyncio.gather(*tasks)
    end_time = time.time()

    success_count = 0
    fail_count = 0

    for status, data in results:
        if status == 200:
            success_count += 1
            print(f"[SUCCESS] {data}")
        else:
            fail_count += 1
            # Uncomment to inspect failure details per request.
            # print(f"[FAILURE] status={status}, detail={data.get('detail')}")

    print("-" * 30)
    print(f"Elapsed time: {end_time - start_time:.4f} seconds")
    print(f"Successful bids (200): {success_count} (expected: 1)")
    print(f"Failed bids (400/429): {fail_count} (expected: 29)")

    if success_count == 1:
        print("Concurrency test passed: only one winning bid was accepted.")
    else:
        print("Concurrency test failed: multiple bids were accepted concurrently.")


if __name__ == "__main__":
    asyncio.run(main())