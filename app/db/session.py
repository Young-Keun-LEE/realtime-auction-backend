from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

# 1. Create async database engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True,  # Log SQL queries (useful for debugging)
    future=True
)

# 2. Session factory
# A new AsyncSession instance will be created for each incoming request
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

# 3. Dependency function for FastAPI
# Used in endpoints as: db: AsyncSession = Depends(get_db)
async def get_db():
    async with AsyncSessionLocal() as session:
        try:    
            yield session           
        finally:
            await session.close()