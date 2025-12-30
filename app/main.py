from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.core.config import settings
from app.db.session import engine
from app.db.models import Base
from app.api.routes import router as api_router

# Lifespan: logic that runs when the app starts and stops
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. On server startup: create database tables if they do not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created!")

    # Application runs and serves requests between yield and the code below
    yield

    # 2. On server shutdown: clean up resources if needed
    print("🛑 Shutting down...")

app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def health_check():
    return {"status": "ok", "message": "Auction Server is Running! 🚀"}