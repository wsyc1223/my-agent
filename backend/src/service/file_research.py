import uuid
import os
import hashlib
import asyncio
import json
from src.utils.notifier import notifier_manager
from langchain_core.messages import AIMessage, ToolMessage, AIMessageChunk
from src.eval_service.task import evaluate_trace_task
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from concurrent.futures import ThreadPoolExecutor
from src.file_research.parser import decode_text_file, chunk_text, chunk_text_with_line
from src.rag import embed_text
from src.db.session import AsyncSessionLocal
from src.schemas import ReportRequest
from src.db.repository import FileDocumentRepository, FileChunkRepository, FileReportRepository, MessageRepository, AsyncTaskRepository
from src.db.model import FileDocument
from src.file_research.research_graph import research_app
from src.observability import get_langfuse_handler
from typing import AsyncGenerator

file_indexing_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="file_indexing"
)

async def handle_file_upload(
    user_id: str,
    filename: str,
    file_path,
    db: AsyncSession,
    background_tasks: BackgroundTasks
) -> dict:
    """
    第一阶段：API 接收端。用户上传文件时, 快速完成哈希校验和秒传判断，非秒传则开启后台计算并快速返回。
    """
    doc_repo = FileDocumentRepository(db)

    with open(file_path, "rb") as f:
        file_data = f.read()

    try:
        os.remove(file_path)
    except Exception as e:
        pass

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
):
    """
    第二阶段： 后台静默计算端。 在独立的数据库会话中运行解析、切块、向量计算和批量插入。
    """
    # 使用独立的生命周期 Session， 防止请求结束之后链接断开
    async with AsyncSessionLocal() as session:
        doc_repo = FileDocumentRepository(session)
        chunk_repo = FileChunkRepository(session)

        try:
            file = await session.get(FileDocument, document_id)
            file_data = file.full_content

            # B. 文本滑动窗口切块
            chunks = chunk_text_with_line(file_data)

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

active_tasks: dict[str, asyncio.Task] = {}

async def run_research_in_background(
    query: str,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID
) -> None:
    """ 后台静默运行子 Agent 图任务， 并负责状态追踪与防御性状态回收"""
    async with AsyncSessionLocal() as session:
        msg_repo = MessageRepository(session) 
        task_repo = AsyncTaskRepository(session)
        report_repo = FileReportRepository(session)

        # 获取到当前的最后一条消息的 id, 就是当前任务的回溯消息id
        latest_msg = await msg_repo.get_latest_user_message(conversation_id=conversation_id)
        trigger_message_id = latest_msg.id if latest_msg else None

        # 首先创建一个任务存库
        task = await task_repo.create(
            user_id=user_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            task_type="deep_research"
        )

        # 存报告入库
        report = await report_repo.create(
            user_id=user_id,
            conversation_id=conversation_id,
            task_id=task.id,
            trigger_message_id=trigger_message_id
        )

        # 记录当前的后台任务 id
        current_task = asyncio.current_task()
        active_tasks[str(task.id)] = current_task

        # 组装图状态
        try:
            input_state = {
                "messages": [("user", query)],
                "file_ids": []
            }

            # 监测
            handler = get_langfuse_handler(
                trace_id=task.id.hex,
                user_id=str(user_id),
                tags=["deep_research"]
            )

            config = {
                "configurable": {
                    "thread_id": str(task.id),
                    "user_id": str(user_id)
                },
                "metadata": {
                    "langfuse_user_id": str(user_id),
                    "langfuse_tags": ["deep_research"]
                },
                "callbacks": [handler]
            }

            # 调佣深度研究图
            await research_app.ainvoke(input_state, config=config)

            # 获取图状态
            final_state = await research_app.aget_state(config)
            report_md = final_state.values.get("report_md", "")

            # 存库
            await report_repo.update_report(
                report_id=report.id,
                status="success",
                report_md=report_md
            )

            # 跟新任务状态
            await task_repo.update_status(task.id, "success")

            handler.langfuse_client.flush()
            await evaluate_trace_task.kiq(
                trace_id=task.id.hex,
                user_id=str(user_id)
            )

            new_msg = await msg_repo.add(
                conversation_id=conversation_id,
                role="subagent",
                content="深度研究报告已生成，点击下方卡片查看详情。",
                referred_message_id=trigger_message_id,
                associated_task_id=task.id
            )

            # 向前端发起广播通知
            await notifier_manager.send_message(
                conversation_id=str(conversation_id),
                data={
                    "type": "subagent_result",
                    "task": {
                        "id": str(task.id),
                        "task_type": "deep_research",
                        "report_id": str(report.id),
                        "status": "success"
                    },
                    "message": {
                        "id": new_msg.id,
                        "role": new_msg.role,
                        "content": new_msg.content,
                        "referred_message_id": trigger_message_id,
                        "associated_task_id": str(task.id)
                    }
                }
            )

        except asyncio.CancelledError:
            await report_repo.update_report(
                report_id=report.id,
                status="error",
                error_message="用户已取消任务"
            )
            await task_repo.update_status(task.id, "stopped", "用户已取消任务")

            stop_msg = await msg_repo.add(
                conversation_id=conversation_id,
                role="subagent",
                content="深度研究任务已经被手动终止",
                referred_message_id=trigger_message_id,
                associated_task_id=task.id
            )

            await notifier_manager.send_message(
                conversation_id=str(conversation_id),
                data={
                    "type": "subagent_result",
                    "task": {
                        "id": str(task.id),
                        "task_type": "deep_research",
                        "status": "stopped",
                        "report_id": str(report.id)
                    },
                    "message": {
                        "id": stop_msg.id,
                        "role": stop_msg.role,
                        "content": stop_msg.content,
                        "referred_message_id": trigger_message_id,
                        "associated_task_id": str(task.id)
                    }
                }
            )
            raise

        except Exception as e:
            await report_repo.update_report(
                report_id=report.id,
                status="error",
                error_message=str(e)
            )
            await task_repo.update_status(task.id, "failed", str(e))
            fail_msg = await msg_repo.add(
                conversation_id=conversation_id,
                role="subagent",
                content=f"深度研究任务执行失败: {str(e)}",
                referred_message_id=trigger_message_id,
                associated_task_id=task.id
            )

            await notifier_manager.send_message(
                conversation_id=str(conversation_id),
                data={
                    "type": "subagent_result",
                    "task": {
                        "id": str(task.id),
                        "task_type": "deep_research",
                        "report_id": str(report.id),
                        "status": "failed",
                        "error_message": str(e)
                    },
                    "message": {
                        "id": fail_msg.id,
                        "role": fail_msg.role,
                        "content": fail_msg.content,
                        "referred_message_id": trigger_message_id,
                        "associated_task_id": str(task.id)
                    }
                }
            )
        finally:
            active_tasks.pop(str(task.id), None)
