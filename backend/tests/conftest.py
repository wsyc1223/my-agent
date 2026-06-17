import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.config import settings

@pytest_asyncio.fixture
async def db_session():
    """
    为测试提供隔离的数据库会话依赖，并在测试运行结束后自动释放连接
    """
    # 1. 建立 SQLAlchemy 异步引擎
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    # 2. 建立 Session 工厂
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 3. 产生会话以供测试代码使用
    async with async_session() as session:
        yield session

    # 4. 测试结束后关闭引擎
    await engine.dispose()
