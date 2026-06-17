import uuid
import asyncio
from sqlalchemy import select
from src.db.session import AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession 
from src.utils.security import get_current_user
from src.db.session import get_db
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from src.db.model import FileDocument, FileChunk, FileReport 
from src.db.repository import FileDocumentRepository, FileChunkRepository, FileReportRepository
from src.rag import embed_text, reranker_model 

async def vector_search_chunks(
    session: AsyncSession,
    query: str,
    user_id: str,
    ids: list[uuid.UUID] | None = None,
    limit: int = 5
) -> list[dict]:
    """ 向量检索: pgvector 粗筛"""
    embed_query = await asyncio.to_thread(embed_text, query) 

    # 构建 ORM 查询
    # Message.embedding.cosine_distance(embed_query) 对应 SQL 中的 <=> 运算符
    # cosine_distance 返回余弦距离(0 - 2), 相似度为 1 - 距离
    similarity = (1 - FileChunk.embedding.cosine_distance(embed_query)).label("score")

    stmt = (
        select(FileChunk, FileDocument.filename, similarity)
        .join(FileDocument, FileChunk.document_id == FileDocument.id)
        .where(FileChunk.user_id == user_id)
        .where(FileChunk.embedding.is_not(None))
        .where(FileDocument.status == "indexed")
    )

    # 如果用户传入了文件，就在用户的文件里面进行检索，否则在用户的所有文件里面检索
    if ids:
        stmt = stmt.where(FileChunk.document_id.in_(ids))

    stmt = stmt.order_by(FileChunk.embedding.cosine_distance(embed_query)).limit(limit * 4)

    result = await session.execute(stmt)
    rows = result.all()
    if not rows:
        return []

    candidates = [
        {
            "chunk_id": int(row[0].id),
            "document_id": str(row[0].document_id),
            "filename": str(row[1]),
            "content": str(row[0].content),
            "start_line": int(row[0].start_line),
            "end_line": int(row[0].end_line),
            "score": float(row[2])
        }
        for row in rows
    ]

    pairs = [(query, c["content"]) for c in candidates]
    scores = await asyncio.to_thread(reranker_model.predict, pairs)
    for i, c in enumerate(candidates):
        c["score"] = float(scores[i])

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]

async def grep_search_chunks(
    session: AsyncSession,
    user_id: str,
    keyword: str,
    ids: list[uuid.UUID] | None = None,
    limit: int = 10
) -> list[dict]:
    """ 精确文本匹配: ILIKE 子串查找， 用于代码变量、配置项、日志关键词"""
    stmt = (
        select(FileChunk, FileDocument)
        .join(FileDocument, FileChunk.document_id == FileDocument.id)
        .where(FileChunk.user_id == user_id)
        .where(FileDocument.status == "indexed")
        .where(FileChunk.content.ilike(f"%{keyword}%"))
    )
    if ids:
        stmt = stmt.where(FileChunk.document_id.in_(ids))

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return [
        {
            "chunk_id": int(row[0].id),
            "document_id": str(row[0].document_id),
            "filename": row[1].filename,
            "content": row[0].content,
            "start_line": row[0].start_line,
            "end_line": row[0].end_line
        }
        for row in result.all()
    ]

@tool
async def search_document_by_vector(query: str, config: RunnableConfig) -> str:
    """
    使用向量语义相似度在用户上传的文档中搜索相关内容，
    适用于寻找定义、概念理解或者是总结性提问。
    """
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")
    doc_ids_row = configurable.get("document_ids", None)

    if not user_id:
        return "错误: 未传入合法的 user_id 授权"

    ids = [uuid.UUID(d) for d in doc_ids_row] if doc_ids_row else None

    async with AsyncSessionLocal() as session:
        res = await vector_search_chunks(session=session, user_id=user_id, query=query, ids=ids)
        if not res:
            return "未在文档中检索到相似结果"
        return "\n\n".join(
            f"【来源: {r['filename']}#L{r['start_line']}-L{r['end_line']}(ID:{r['chunk_id']})】\n{r['content']}"
            for r in res
        )

@tool
async def search_document_by_grep(keyword: str, config: RunnableConfig) -> str:
    """
    使用精确字符匹配(类似于 Linux grep) 查找特定变量名、函数定义、类名或者是配置参数。
    """

    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")
    doc_ids_row = configurable.get("document_ids")

    if not user_id:
        return "错误: 未传入合法的 user_id 授权"

    ids = [uuid.UUID(d) for d in doc_ids_row] if doc_ids_row else None

    async with AsyncSessionLocal() as session:
        res = await grep_search_chunks(session, user_id, keyword=keyword, ids=ids)
        if not res:
            return f"未找到包含字符 '{keyword}' 的代码片段"
        return "\n\n".join(
            f"【来源: {r['filename']}#L{r['start_line']}-L{r['end_line']}(ID:{r['chunk_id']})】\n{r['content']}"
            for r in res
        )
