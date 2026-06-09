import uuid
import os
import hashlib
import asyncio
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from concurrent.futures import ThreadPoolExecutor
from src.file_research.parser import decode_text_file, chunk_text
from src.rag import embed_text
from src.db.session import AsyncSessionLocal
from src.db.repository import FileDocumentRepository, FileChunkRepository

file_indexing_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="file_indexing"
)
async def handle_file_upload(
    user_id: str,
    filename: str,
    file_data: bytes,
    db: AsyncSession,
    background_tasks: BackgroundTasks
) -> dict:
    """
    第一阶段：API 接收端。 快速完成哈希校验和秒传判断， 非秒传则开启后台计算并快速返回。
    """
    doc_repo = FileDocumentRepository(db)

    # 1. 计算文件 SHA256 哈希值
    sha256 = hashlib.sha256(file_data).hexdigest()

    # 2. 秒传判定
    existing = await doc_repo.get_by_sha256(user_id, sha256)
    if existing:
        if existing.status == "indexed":
            # 状态为成功，直接秒传复用
            return {
                "status": "indexed",
                "document_id": str(existing.id),
                "filename": existing.filename,
                "message": "秒传成功（已复用历史解析记录）"
            }
        elif existing.status == "failed":
            # 上次上传崩溃了，清理掉废弃的记录然后重新上传
            await doc_repo.delete(user_id, existing.id)

    # 3. 如果是新文件，创建状态为 “processing" 的记录
    doc = await doc_repo.create(user_id, filename, len(file_data), sha256, status="processing")

    # 4. 开启异步后处理任务，把 doc.id 以及文件数据丢进后台，让 HTTP 链接立刻释放
    background_tasks.add_task(
        process_file_in_background,
        doc.id,
        user_id,
        filename,
        file_data
    )

    return {
        "status": "processing",
        "document_id": str(doc.id),
        "filename": filename,
        "message": "文件上传成功，正在后台解析与计算向量中，请稍后..."
    } 

async def process_file_in_background(
    document_id: uuid.UUID,
    user_id: str,
    filename: str, 
    file_data: bytes
):
    """
    第二阶段： 后台静默计算端。 在独立的数据库会话中运行解析、切块、向量计算和批量插入。
    """
    # 使用独立的生命周期 Session， 防止请求结束之后链接断开
    async with AsyncSessionLocal() as session:
        doc_repo = FileDocumentRepository(session)
        chunk_repo = FileChunkRepository(session)

        try:
            # A. 解码文本文件
            parsed_file = decode_text_file(filename, file_data)

            # B. 文本滑动窗口切块
            chunks = chunk_text(parsed_file.text)

            # C. 批量生成向量
            # 使用 asyncio.gather 和 asyncio.to_thread， 将所有切块并行分发到线程池中计算向量
            # 获取当前的事件循环对象
            loop = asyncio.get_running_loop()

            embeddings = await asyncio.gather(*[
                loop.run_in_executor(file_indexing_executor, embed_text,  chunk)
                for chunk in chunks
            ])

            # D. 组装数据并批量写入数据库
            chunks_data = [
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "chunk_index": idx,
                    "content": chunk,
                    "token_estimate": len(chunk),
                    "embedding": emb
                }
                for idx, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ]
            await chunk_repo.bulk_create(chunks_data)

            # E. 跟新文件状态为 indexed
            await doc_repo.update_status(document_id, "indexed")

        except Exception as e:
            await doc_repo.update_status(document_id, "failed", error_message=str(e))

