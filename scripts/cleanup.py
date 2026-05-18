"""Utility script to clear all application data.

This script truncates PostgreSQL tables and flushes all Redis keys.
Usage: python scripts/cleanup.py
"""

import subprocess
import sys
from pathlib import Path


def load_env_file() -> dict[str, str]:
    """Load simple KEY=VALUE pairs from the project .env file."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    values: dict[str, str] = {}

    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


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
    env_values = load_env_file()
    postgres_user = env_values.get("POSTGRES_USER", "postgres")
    postgres_db = env_values.get("POSTGRES_DB", "postgres")

    return run_command(
        [
            "docker",
            "exec",
            "auction_db",
            "psql",
            "-U",
            postgres_user,
            "-d",
            postgres_db,
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
