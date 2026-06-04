from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings

DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, class_ = AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
