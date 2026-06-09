import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, delete, insert
from sqlalchemy.orm import selectinload
from src.db.model import Conversation, Message, FileDocument, FileChunk, FileReport
from sqlalchemy import text

class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        conv = Conversation(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title
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


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, conversation_id: uuid.UUID, role: str, content: str, tool_calls: dict | None = None) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg

    async def get_history(self, conversation_id: uuid.UUID) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def count(self, conversation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(Message).where(Message.conversation_id == conversation_id)
        )
        return len(list(result.scalars().all()))
    
    async def set_embedding(self, message_id: int, embedding: list[float]) -> None:
        await self.session.execute(
            text("UPDATE messages SET embedding = cast(:emb as vector) WHERE id = :mid"),
            {"emb": str(embedding), "mid": message_id}
        )
        await self.session.commit()

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

    async def create(self, user_id: str, filename: str, size_bytes: int, sha256: str, status: str = "processing") -> FileDocument:
        """
        新建文件记录，默认为 processing（处理中）状态。
        """
        doc = FileDocument(
            id=uuid.uuid4(),
            user_id=user_id,
            filename=filename,
            size_bytes=size_bytes,
            sha256=sha256,
            status=status
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

class FileReportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, query: str) -> FileReport:
        report = FileReport(
            id=uuid.uuid4(),
            user_id=user_id,
            query=query,
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
