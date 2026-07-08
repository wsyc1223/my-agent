from sentence_transformers import SentenceTransformer, CrossEncoder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from src.db.model import Message, Conversation
import os
import asyncio


embedding_model_path = os.path.join(os.path.dirname(__file__), "models", "bge-base-zh-v1.5")
embedding_model = SentenceTransformer(embedding_model_path)
embedding_model.encode = lambda *a, **kw: SentenceTransformer.encode(embedding_model, *a, **kw, show_progress_bar=False)

reranker_model_path = os.path.join(os.path.dirname(__file__), "models", "bge-reranker-base")
reranker_model = CrossEncoder(reranker_model_path)

def embed_text(text: str) -> list[float]:
    if not text or not text.strip():
        return [0.0] * 768
    return embedding_model.encode(text, normalize_embeddings=True).tolist()

async def search_messages(session: AsyncSession, user_id: str, query: str, exclude_conversation_id = None, limit: int = 5):
    # 生成异步向量
    query_vec = await asyncio.to_thread(embed_text, query)
    
    # 构建 ORM 查询
    # Message.embedding.cosine_distance(query_vec) 对应 SQL 中的 <=> 运算符
    # cosine_distance 返回余弦距离(0 - 2), 相似度为 1 - 距离
    similarity = (1 - Message.embedding.cosine_distance(query_vec)).label("score")

    stmt = (
        select(Message.content, Message.role, similarity)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .where(Message.embedding.is_not(None))
    )

    # 动态且类型安全的加入可选过滤条件
    if exclude_conversation_id:
        stmt = stmt.where(Conversation.id != exclude_conversation_id)

    # 排序并限制召回数量
    stmt = stmt.order_by(Message.embedding.cosine_distance(query_vec)).limit(limit * 4)


    # 执行查询
    result = await session.execute(stmt)

    # 解析结果为 reranker 需要的格式
    candidates = [
        {"content": row.content, "role": row.role, "score": float(row.score)}
        for row in result
    ]
    if candidates:
        pairs = [(query, c["content"]) for c in candidates]
        scores = await asyncio.to_thread(reranker_model.predict, pairs)

        for i, c in enumerate(candidates):
            c["score"] = float(scores[i])
        candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:limit]
