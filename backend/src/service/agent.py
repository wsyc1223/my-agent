from src.graph import app 
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk
from fastapi.responses import StreamingResponse  
from src.db.repository import ConversationRepository, MessageRepository
from sqlalchemy import text
from src.rag import embed_text, search_messages
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession
from src.observability import langfuse_handler 
import json
import uuid
import asyncio

# 流式
async def chat_stream(message: str, user_id: str, db: AsyncSession, global_memory: bool = False, conversation_id: uuid.UUID | None = None):
    async def generator():
        nonlocal conversation_id
        conv_repo = ConversationRepository(db)
        msg_repo = MessageRepository(db)

        # 1.1 如果没有会话 id (新会话),则新建一个会话，如果有会话 id，则使用原来的会话
        if conversation_id is None:
            conv = await conv_repo.create(user_id=user_id, global_memory=global_memory)
            conversation_id = conv.id
        else:
            conv = await conv_repo.get(user_id, conversation_id)
            if conv is None:
                conv = await conv_repo.create(user_id=user_id, global_memory=global_memory)
                conversation_id = conv.id

        is_global_memory_enabled = conv.global_memory


        # 2 把用户的消息转化成为向量存入数据库
        msg = await msg_repo.add(conversation_id, "user", message)
        msg_emb = await asyncio.to_thread(embed_text, message)
        await msg_repo.set_embedding(msg.id, msg_emb)

        # 3 通过计算向量相似度把相关内容加入到提示词里面
        user_message_content = message
        hits = []
        if is_global_memory_enabled:
            hits = await search_messages(db, user_id, message, exclude_conversation_id=conversation_id, limit=5)

        if hits:
            ctx = "以下是你与该用户的历史对话，可供参考: \n" + "\n".join(
                f"- [{h['role']}]: {h['content']}" for h in hits
            )
            user_message_content = f"{ctx}\n\n用户当前问题:{message}"

        # 4 把加强后的提示词加入 HumanMessage
        state_input = {
            "messages": [HumanMessage(content=user_message_content)]
        }

        # 5 统一 ID 并生成 Config
        thread_id = conversation_id
        config = {
            "configurable": {"thread_id": str(thread_id)},
            "callbacks": [langfuse_handler]
        }

        # 6 向前端通知会话建立
        yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': str(conversation_id)})}\n\n"

        # 7 驱动大模型逐步返回消息片段
        try:
            async for msg, metadata in app.astream(
                state_input, config, stream_mode="messages"
            ):
                # 7.1 如果 msg 里面包含 AIMessageChunk(说明是 AI 返回的消息片段)， 就返回到前端
                if isinstance(msg, AIMessageChunk):
                    if msg.content:
                        val = msg.content.replace(chr(10), '\\n')
                        yield f"data: {json.dumps({'type': 'text', 'content': val})}\n\n"
                        await asyncio.sleep(0.01)

            # 7.2 这里只获取最后一条消息，因为chat_stream 只会返回一条 llm 的消息，以后如果有逻辑需要修改可以改
            state = await app.aget_state(config)
            last_msg = state.values["messages"][-1]

            # 7.3 把 AI 返回的消息存进数据库， 这里只需要存储 AIMessage 即可
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                rep = await msg_repo.add(conversation_id, "assistant", last_msg.content or "", last_msg.tool_calls)
            elif isinstance(last_msg, AIMessage):
                rep = await msg_repo.add(conversation_id, "assistant", last_msg.content)

            # 7.4 把 AI 的消息计算向量然后存进数据库    
            rep_emb = await asyncio.to_thread(embed_text, last_msg.content)
            await msg_repo.set_embedding(rep.id, rep_emb)

            # 7.5 如果发现有 tools 在图结构里，说明下一步是调工具，则返回给前端 interrupt
            if state.next and "tools" in state.next:
                yield f"data: {json.dumps({'type': 'interrupt', 'thread_id': str(thread_id), 'conversation_id': str(conversation_id)})}\n\n"
            
            # 7.6 结束，返回 done 给前端
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        
        # 8 遇到错误，返回错误消息
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        # 9 如果发现是新会话(没有标题，新建标题)，这里后期可以修改让新建标题的逻辑更加完善
        if not conv.title:
            await conv_repo.update_title(user_id, conversation_id, message[:50])

    return StreamingResponse(generator(),
                            media_type="text/event-stream",
                            headers={
                            "Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no",
                            "Connection": "keep-alive",
                            },)


async def resume(thread_id: uuid.UUID, approved: bool, db: AsyncSession, conversation_id: uuid.UUID):
    async def generator():
        nonlocal thread_id
        msg_repo = MessageRepository(db)

        # 2 获取之前被中断的消息的状态，并且记录里面的目前消息条数 before_count
        config = {"configurable": {"thread_id": str(thread_id)}, "callbacks": [langfuse_handler]}
        state = await app.aget_state(config)
        before_count = len(state.values["messages"])

        # 3 如果说此时用户点击了拒绝调用工具，则工具消息加入拒绝的消息, 如果用户同意则命令为continue
        if not approved:
            state = await app.aget_state(config)
            last_msg = state.values["messages"][-1]
            tool_calls = getattr(last_msg, "tool_calls", []) or []
            tool_message = [
                ToolMessage(content="用户拒绝了该工具的调用", tool_call_id=tc["id"])
                for tc in tool_calls  
            ]
            resume_input = Command(resume={"messages": tool_message})
        else:
            # 3.1 批准工具执行，设置 resume 命令为 continue
            resume_input = Command(resume="continue")
            # 3.2 提取大模型在此回合即将并发调用的所有工具名称列表
            last_msg = state.values["messages"][-1]
            tool_names = [tc["name"] for tc in last_msg.tool_calls] if getattr(last_msg, "tool_calls", None) else ["tool"]

            yield f"data: {json.dumps({'type': 'tool_run', 'tool_names': tool_names})}\n\n"

        # 4 驱动大模型返回消息
        try:
            async for msg, metadata in app.astream(
                resume_input, config, stream_mode="messages"
            ):
                # 5 如果 msg 里面包含AIMessageChunk，则返回给前端展示
                if isinstance(msg, AIMessageChunk):
                    if msg.content:
                        val = msg.content.replace(chr(10), '\\n')
                        yield f"data: {json.dumps({'type': 'text', 'content': val})}\n\n"
                        await asyncio.sleep(0.01)

            # 6 获取此时的图状态
            state = await app.aget_state(config)

            # 7 从之前记录的最后一条消息开始一直到当前的最后一条消息遍历
            for msg in state.values["messages"][before_count:]:
                # 7.1 如果是 AI 消息并且带有 tool_calls， 直接加入数据库库然后保存向量
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    rep = await msg_repo.add(conversation_id, "assistant", msg.content or "", msg.tool_calls)
                    rep_emb = await asyncio.to_thread(embed_text, msg.content)
                    await msg_repo.set_embedding(rep.id, rep_emb)
                # 7.2 如果是工具消息，直接加入数据库即可
                elif isinstance(msg, ToolMessage):
                    await msg_repo.add(conversation_id, "tool", msg.content, {"tool_call_id": msg.tool_call_id})
                # 7.3 如果是纯 AI 消息，直接加入数据库库然后保存向量
                elif isinstance(msg, AIMessage):
                    rep = await msg_repo.add(conversation_id, "assistant", msg.content)
                    rep_emb = await asyncio.to_thread(embed_text, msg.content)
                    await msg_repo.set_embedding(rep.id, rep_emb)

            # 8 如果发现有 tool_calls 在图结构里，返回interrupt给前端
            if state.next and "tools" in state.next:
                yield f"data: {json.dumps({'type': 'interrupt', 'thread_id': str(thread_id), 'conversation_id': str(conversation_id)})}\n\n"

            # 9 发送 done 给前端
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        #  10 如果有错误，发送错误消息给前端
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(generator(), 
                             media_type="text/event-stream",
                             headers={
                                "Cache-Control": "no-cache",
                                "X-Accel-Buffering": "no",
                                "Connection": "keep-alive",
                             },)
