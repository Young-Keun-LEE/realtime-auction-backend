import os
from pydantic_settings import BaseSettings
from pydantic import model_validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "Realtime Auction"
    API_V1_STR: str = "/api/v1"
    
    # Current runtime environment (default: 'local' for development)
    ENV: str = "local"
    
    # Default fallback values for local development
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "auction_db"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    
    REDIS_URL: str = "redis://redis:6379"
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_BID_TOPIC: str = "auction-bids"

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    # Security: enforce validation of production credentials
    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        # If running in production, reject default/placeholder credentials and fail fast
        if self.ENV == "production":
            if self.POSTGRES_PASSWORD == "postgres" or "redis://redis:6379" in self.REDIS_URL:
                raise ValueError(
                    "SECURITY ERROR: Running in production requires real, non-default credentials.\n"
                    "Set secure Postgres and Redis credentials via environment variables; default values are prohibited."
                )
        return self

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()