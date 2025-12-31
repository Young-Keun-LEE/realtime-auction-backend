"""Utility script to clear all application data.

This script truncates PostgreSQL tables and flushes all Redis keys.
Usage: python scripts/cleanup.py
"""

import subprocess
import sys


def run_command(command: list[str], description: str) -> bool:
    """Run a shell command and return whether it succeeded."""
    print(f"[INFO] {description}...")
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"[INFO] {description} completed successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[ERROR] {description} failed: {exc.stderr}")
        return False


def cleanup_postgres() -> bool:
    """Truncate all application tables and reset identity sequences in PostgreSQL."""
    return run_command(
        [
            "docker",
            "exec",
            "auction_db",
            "psql",
            "-U",
            "user",
            "-d",
            "auction",
            "-c",
            "TRUNCATE bids, auctions, users RESTART IDENTITY CASCADE;",
        ],
        "Cleaning PostgreSQL data",
    )


def cleanup_redis() -> bool:
    """Remove all keys from the Redis instance used by the application."""
    return run_command(
        ["docker", "exec", "auction_redis", "redis-cli", "FLUSHALL"],
        "Cleaning Redis data",
    )


def main() -> None:
    """Entry point for the cleanup script."""
    print("Data cleanup (PostgreSQL + Redis) will remove all application data.\n")

    confirm = input("Are you sure you want to continue? (y/N): ")
    if confirm.lower() != "y":
        print("Aborted by user.")
        sys.exit(0)

    print()

    postgres_ok = cleanup_postgres()
    redis_ok = cleanup_redis()

    print()
    if postgres_ok and redis_ok:
        print("Cleanup finished successfully. All application data has been removed.")
    else:
        print("Cleanup finished with errors. Some resources may not have been cleared.")
        sys.exit(1)


if __name__ == "__main__":
    main()
