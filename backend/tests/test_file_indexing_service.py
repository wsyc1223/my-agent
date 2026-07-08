import pytest
import uuid
from src.service.file_research import process_file_in_background
from src.db.repository import FileDocumentRepository, FileChunkRepository
from src.db.model import User # 引入 User 

# 声明这是一个异步测试，pytest-asyncio 会自动为你调度事件循环
@pytest.mark.asyncio
async def test_process_file_in_background_saving_lines(db_session):
    """
    测试点：模拟上传文本文件后，验证后台计算全链路是否能正常落库，
    并且 full_content、start_line、end_line 的数据写入是否正确。
    """
    # 1. 先创建真实的测试用户以满足外键约束
    test_user = User()
    db_session.add(test_user)
    await db_session.commit()
    await db_session.refresh(test_user)

    user_id = str(test_user.id)
    doc_repo = FileDocumentRepository(db_session)

    # 1. 准备假数据并创建初始“处理中（processing）”的记录
    filename = "sample_code.py"
    content = b"def first_func():\n    pass\n\ndef second_func():\n    return True"
    doc = await doc_repo.create(
        user_id=user_id,
        filename=filename,
        size_bytes=len(content),
        sha256="mock_sha256_hash",
        status="processing",
        full_content=content.decode("utf-8") # 👈 写入全文
    )

    # 2. 执行后台向量化入库服务
    # 针对 pytest 事务隔离，使用 mock patch 让后台任务复用测试的 db_session
    from unittest.mock import patch
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_local():
        yield db_session

    with patch("src.service.file_research.AsyncSessionLocal", mock_session_local):
        await process_file_in_background(doc.id, user_id, filename)

    # 3. 校验文档状态：验证是否成功变更为 indexed，且 full_content 是否被保存
    updated_doc = await db_session.get(type(doc), doc.id)
    assert updated_doc.status == "indexed"
    assert updated_doc.full_content == content.decode("utf-8")

# 4. 校验分块与行号数据：查出刚才该文档入库的所有 chunks 记录
    from sqlalchemy import select
    from src.db.model import FileChunk
    res = await db_session.execute(select(FileChunk).where(FileChunk.document_id == doc.id))
    chunks = res.scalars().all()

    assert len(chunks) > 0
# 验证第一个分块，应该记录了它属于第 1 行到第 5 行
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 5
