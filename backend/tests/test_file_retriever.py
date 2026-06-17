import pytest
import uuid
from src.db.model import User, FileDocument, FileChunk
from src.file_research.retriever import grep_search_chunks, search_document_by_grep
from langchain_core.runnables import RunnableConfig
from unittest.mock import patch
from contextlib import asynccontextmanager

@pytest.mark.asyncio
async def test_hybrid_retrieval_logic(db_session):
    test_user = User()
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)
    user_id = str(test_user.id)

    doc = FileDocument(
        id=uuid.uuid4(),
        user_id=test_user.id,
        filename="test_search.py",
        size_bytes=100,
        sha256="sha256_search",
        status="indexed",
        full_content="def my_secret_function():\n    pass"
    )
    db_session.add(doc)
    await db_session.commit()

    chunk = FileChunk(
        document_id=doc.id,
        user_id=test_user.id,
        chunk_index=0,
        content="def my_secret_function():\n    pass",
        embedding=[0.1] * 768,
        start_line=1,
        end_line=2
    )
    db_session.add(chunk)
    await db_session.commit()

    # Grep 精确匹配
    grep_res = await grep_search_chunks(db_session, user_id, "my_secret_function")
    assert len(grep_res) == 1
    assert grep_res[0]["filename"] == "test_search.py"
    assert grep_res[0]["start_line"] == 1

    # 异步 Tool 测试
    config = RunnableConfig(configurable={"user_id": user_id})

    @asynccontextmanager
    async def mock_session_local():
        yield db_session

    with patch("src.file_research.retriever.AsyncSessionLocal", mock_session_local):
        tool_res = await search_document_by_grep.ainvoke(
            {"keyword": "my_secret_function"}, config=config
        )
        assert "【来源: test_search.py#L1-L2" in tool_res
        assert "def my_secret_function" in tool_res
