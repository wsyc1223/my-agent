import uuid
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, insert
from sqlalchemy.orm import selectinload
from src.db.model import Conversation, Message, FileDocument, FileChunk, FileReport, AsyncTask
from sqlalchemy import text

class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, title: str | None = None, global_memory: bool = False) -> Conversation:
        conv = Conversation(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            global_memory=global_memory
        )
        self.session.add(conv)
        await self.session.commit()
        await self.session.refresh(conv)
        return conv 

    async def get(self, user_id:str, conversation_id: uuid.UUID) -> Conversation | None:
        conv = await self.session.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            return None
        else:
            return conv

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.updated_at))
        )
        return list(result.scalars().all())

    async def update_title(self,user_id:str, conversation_id: uuid.UUID, title: str) -> None:
        conv = await self.session.get(Conversation, conversation_id)
        if conv and conv.user_id == user_id:
            conv.title = title
            await self.session.commit()

    async def delete(self, user_id: str | uuid.UUID, conversation_id: uuid.UUID) -> bool:
        conv = await self.session.get(Conversation, conversation_id)
        if conv and str(conv.user_id) == str(user_id):
            await self.session.execute(
                delete(FileReport)
                .where(FileReport.conversation_id == conversation_id)
                .where(FileReport.is_saved == False)
            )
            await self.session.delete(conv)
            await self.session.commit()
            return True
        return False

class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # 新增消息记录
    async def add(self, conversation_id: uuid.UUID,
                  role: str,
                  content: str,
                  tool_calls: dict | None = None,
                  referred_message_id: int | None = None,
                  associated_task_id: uuid.UUID | None = None) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            referred_message_id=referred_message_id,
            associated_task_id=associated_task_id
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    # 获取消息历史
    async def get_history(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .options(selectinload(Message.associated_task).selectinload(AsyncTask.file_report))
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def count(self, conversation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        )
        return result.scalar_one()
 
    async def set_embedding(self, message_id: int, embedding: list[float]) -> None:
        await self.session.execute(
            text("UPDATE messages SET embedding = cast(:emb as vector) WHERE id = :mid"),
            {"emb": str(embedding), "mid": message_id}
        )
        await self.session.commit()

    async def get_latest_user_message(self, conversation_id: uuid.UUID) -> Message | None:
        """
        极速获取当前会话中，用户发送的最新一条消息(O(1)索引检索，不加载历史)
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role == "user")
            .order_by(desc(Message.id))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

class FileDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_sha256(self, user_id: str, sha256:str) -> FileDocument | None:
        """
        根据哈希值查询该用户的历史文件。
        """

        stmt = (
            select(FileDocument)
            .where(FileDocument.user_id == user_id)
            .where(FileDocument.sha256 == sha256)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, user_id: str, filename: str, size_bytes: int, sha256: str, status: str = "processing", full_content: str | None = None) -> FileDocument:
        """
        新建文件记录，默认为 processing（处理中）状态。
        """
        doc = FileDocument(
            id=uuid.uuid4(),
            user_id=user_id,
            filename=filename,
            size_bytes=size_bytes,
            sha256=sha256,
            status=status,
            full_content=full_content
        )
        self.session.add(doc)
        await self.session.commit()
        await self.session.refresh(doc)
        return doc

    async def update_status(self, document_id: uuid.UUID, status: str, error_message: str | None = None) -> None:
        """
        更新文件解析状态与错误信息
        """
        # self.session.get() 是 SQLAlchemy 的主键查询快捷方式， 比 select(...) 性能更好
        doc = await self.session.get(FileDocument, document_id)
        if doc:
            doc.status = status
            doc.error_message = error_message
            await self.session.commit()

    async def list_by_user(self, user_id: str) -> list[FileDocument]:
        """
        获取用户的文件列表，按上传时间倒序。
        """
        stmt = (
            select(FileDocument)
            .where(FileDocument.user_id == user_id)
            .order_by(desc(FileDocument.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, user_id: str, document_id: uuid.UUID) -> bool:
        """
        删除文件 （因为联级关系， 对应的 file_chunks 会被数据库一同清空）
"""
        doc = await self.session.get(FileDocument, document_id)
        # 安全性校验： 必须确保该文件属于当前用户， 防止越权删除别人的文件
        if doc and str(doc.user_id) == str(user_id):
            await self.session.delete(doc)
            await self.session.commit()
            return True
        return False

class FileChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_create(self, chunks_data: list[dict]) -> None:
        """
        批量插入切块。
        """
        if not chunks_data:
            return

        # 1. 构建 bulk insert 语句
        # insert(FileChunk) 对应 INSERT INTO file_chunks ...
        # 当把 chunks_data (字典列表) 传给 execute() 时， SQLAlchemy
        # 会将其编译成一条多行的 VALUES 语句： INSERT INTO ...VALUES(...), (...), (...)
        # 这在底层只与数据库通信一次，性能高很多
        await self.session.execute(
            insert(FileChunk),
            chunks_data
        )
        # 2. 提交事务
        await self.session.commit()

# class ResearchSessionRepository:
#     def __init__(self, session: AsyncSession):
#         self.session = session
#
#     async def create(self, user_id: str | uuid.UUID, title: str | None = None) -> ResearchSession:
#         new_session = ResearchSession(
#             user_id=user_id,
#             title=title
#         )
#         self.session.add(new_session)
#         await self.session.commit()
#         await self.session.refresh(new_session)
#         return new_session
#
#     async def get(self, user_id: str | uuid.UUID, session_id: uuid.UUID) -> ResearchSession | None:
#         res = await self.session.get(ResearchSession, session_id)
#         if res and str(res.user_id) == str(user_id):
#             return res
#         return None
#
#     async def list_by_user(self, user_id: str | uuid.UUID) -> list[ResearchSession]:
#         result = await self.session.execute(
#             select(ResearchSession)
#             .where(ResearchSession.user_id == user_id)
#             .order_by(desc(ResearchSession.updated_at))
#         )
#         return list(result.scalars().all())

# class ResearchMessageRepository:
#     def __init__(self, session: AsyncSession):
#         self.session = session
#
#     async def add(self, session_id: uuid.UUID, role: str, content: str | None,
#                   tool_calls: dict | None = None, attached_file_ids: list | None = None,
#                   generated_report_id: uuid.UUID | None = None) -> ResearchMessage:
#         new_msg = ResearchMessage(
#             session_id=session_id,
#             role=role,
#             content=content,
#             tool_calls=tool_calls,
#             attached_file_ids=attached_file_ids,
#             generated_report_id=generated_report_id
#         )
#         self.session.add(new_msg)
#         await self.session.commit()
#         await self.session.refresh(new_msg)
#         return new_msg
#
#     async def get_history(self, session_id: uuid.UUID) -> list[ResearchMessage]:
#         stmt = (
#                 select(ResearchMessage)
#                 .where(ResearchMessage.session_id == session_id)
#                 .order_by(ResearchMessage.created_at)
#         )
#
#         result = await self.session.execute(stmt)
#         return list(result.scalars().all())

class FileReportRepository:
    """ 处理 agent 产生的报告 """
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, conversation_id: str, task_id: uuid.UUID | None = None, trigger_message_id: int | None = None) -> FileReport:
        report = FileReport(
            id=uuid.uuid4(),
            user_id=user_id,
            conversation_id=conversation_id,
            task_id=task_id,
            trigger_message_id=trigger_message_id,
            status="running"
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        return report

    async def update_report(self, report_id: uuid.UUID, status: str, report_md: str | None = None, selected_chunk_ids: list | None = None, error_message: str | None = None) -> None:
        report = await self.session.get(FileReport, report_id)
        if report:
            report.status = status
            report.report_md = report_md
            report.selected_chunk_ids = selected_chunk_ids
            report.error_message = error_message
            await self.session.commit()

    async def set_saved_status(self, report_id: uuid.UUID, is_saved: bool = True) -> None:
        """ 修改保存状态 """
        report = await self.session.get(FileReport, report_id)
        if report:
            report.is_saved = is_saved
            await self.session.commit()

    async def list_saved_by_user(self, user_id: uuid.UUID | str) -> list[FileReport]:
        """ 列出用户的所有的保存的文件 """
        stmt = (
            select(FileReport)
            .where(FileReport.user_id == user_id)
            .where(FileReport.is_saved == True)
            .order_by(desc(FileReport.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_by_conversation(self, conversation_id: uuid.UUID) -> FileReport | None:
        result = await self.session.execute(
            select(FileReport)
            .where(FileReport.conversation_id == conversation_id)
            .order_by(desc(FileReport.created_at))
            .limit(1)
        )
        return result.scalars().first()

class AsyncTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self,
                     user_id: uuid.UUID,
                     conversation_id: uuid.UUID,
                     trigger_message_id: int,
                     task_type: str):
        new_task = AsyncTask(
            user_id=user_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            task_type=task_type,
            status="running"
        )
        self.session.add(new_task)
        await self.session.commit()
        await self.session.refresh(new_task)
        return new_task

    async def update_status(self, task_id: uuid.UUID, status: str, error_message: str | None = None) -> None:
        task = await self.session.get(AsyncTask, task_id)
        if task:
            task.status = status
            task.error_message = error_message
            await self.session.commit()
