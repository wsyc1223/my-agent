import uuid
import os
import hashlib
import asyncio
import json
from langchain_core.messages import AIMessage, ToolMessage, AIMessageChunk
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from concurrent.futures import ThreadPoolExecutor
from src.file_research.parser import decode_text_file, chunk_text, chunk_text_with_line
from src.rag import embed_text
from src.db.session import AsyncSessionLocal
from src.schemas import ReportRequest
from src.db.repository import FileDocumentRepository, FileChunkRepository, FileReportRepository, ResearchSessionRepository, ResearchMessageRepository
from src.file_research.research_graph import research_app
from typing import AsyncGenerator

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
    第一阶段：API 接收端。用户上传文件时, 快速完成哈希校验和秒传判断，非秒传则开启后台计算并快速返回。
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
    parserd_file = decode_text_file(filename=filename, data=file_data)
    doc = await doc_repo.create(user_id, filename, len(file_data), sha256, status="processing", full_content=parserd_file.text)

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
            chunks = chunk_text_with_line(parsed_file.text)

            # C. 批量生成向量
            # 使用 asyncio.gather 和 asyncio.to_thread， 将所有切块并行分发到线程池中计算向量
            # 获取当前的事件循环对象
            loop = asyncio.get_running_loop()

            embeddings = await asyncio.gather(*[
                loop.run_in_executor(file_indexing_executor, embed_text,  chunk.content)
                for chunk in chunks
            ])

            # D. 组装数据并批量写入数据库
            chunks_data = [
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "chunk_index": idx,
                    "content": chunk.content,
                    "token_estimate": len(chunk.content),
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "embedding": emb
                }
                for idx, (chunk, emb) in enumerate(zip(chunks, embeddings))
            ]
            await chunk_repo.bulk_create(chunks_data)

            # E. 跟新文件状态为 indexed
            await doc_repo.update_status(document_id, "indexed")

        except Exception as e:
            import traceback
            traceback.print_exc()
            await doc_repo.update_status(document_id, "failed", error_message=str(e))

async def stream_research_session(
    user_id: str,
    session_id: str,
    db: AsyncSession,
    query: str,
    file_ids: list[uuid.UUID] | None
) -> AsyncGenerator[str, None]:
    session_repo = ResearchSessionRepository(db)
    message_repo = ResearchMessageRepository(db)
    report_repo = FileReportRepository(db)

    # 检查会话是否存在，否则返回错误或者是新建会话
    if not session_id:
        rs = await session_repo.create(user_id=user_id, title=query[:20])
        session_id = rs.id
    else:
        rs = await session_repo.get(user_id=user_id, session_id=session_id)
        if not rs:
            yield f"data: {json.dumps({'error': '会话不存在'})}\n\n"
            return

    # 将用户上传的文件 id 转换为 str 格式
    file_ids_str = [str(id) for id in file_ids] if file_ids else []

    # 将用户的提问添加到数据库
    await message_repo.add(
        session_id=session_id,
        role="user",
        content=query,
        attached_file_ids=file_ids_str
    )

    # 组装用户输入
    input_state = {
        "messages": [("user", query)],
        "file_ids": file_ids_str
    }

    # 传入 session_id 作为 thread_id
    config = {"configurable": {"thread_id": str(session_id)}}
    state = await research_app.aget_state(config)
    before_count = len(state.values.get("messages", []))

    report = await report_repo.create(user_id=user_id, session_id=session_id)
    final_report_md = ""

    # 调用大模型，实时监听流式输出
    try:
        async for msg, metadata in research_app.astream(input_state, config=config, stream_mode="messages"):
            node_name = metadata.get("langgraph_node", "unknow")

            if msg.content and isinstance(msg, AIMessageChunk):
                val = msg.content.replace(chr(10), '\\n')

                if node_name == "researcher":
                    yield f"data: {json.dumps({'type': 'chat', 'content': val})}\n\n"
                elif node_name == "writer":
                    yield f"data: {json.dumps({'type': 'report', 'content': val})}\n\n"

            elif hasattr(msg, "tool_calls") and msg.tool_calls:
                for tool in msg.tool_calls:
                    yield f"data: {json.dumps({'type': 'tool', 'tool': tool['name']})}\n\n"

        final_state = await research_app.aget_state(config)
        all_messages = final_state.values.get("messages", [])

        last_msg = all_messages[-1] if all_messages else None
        if last_msg and getattr(last_msg, "content", None):
            final_report_md = last_msg.content

        await report_repo.update_report(
            report_id=report.id,
            status="success",
            report_md=final_report_md
        )

        new_messages = all_messages[before_count:]

        for msg in new_messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                await message_repo.add(
                    session_id=session_id,
                    role="assistant",
                    content=msg.content or "",
                    tool_calls=msg.tool_calls
                )
            elif isinstance(msg, ToolMessage):
                await message_repo.add(
                    session_id=session_id,
                    role="tool",
                    content=msg.content,
                    tool_calls={"tool_call_id": msg.tool_call_id}
                )
            elif isinstance(msg, AIMessage):
                await message_repo.add(
                    session_id=session_id,
                    role="assistant",
                    content=msg.content,
                    generated_report_id=report.id
                )
        yield f"data: {json.dumps({'status': 'done', 'report_id': str(report.id)})}\n\n"

    except Exception as e:
        import traceback
        traceback.print_exc()
        await report_repo.update_report(
            report_id=report.id,
            status="error",
            error_message=str(e)
        )
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
