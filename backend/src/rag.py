from sentence_transformers import SentenceTransformer, CrossEncoder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os

embedding_model_path = os.path.join(os.path.dirname(__file__), "models", "bge-base-zh-v1.5")
embedding_model = SentenceTransformer(embedding_model_path)
embedding_model.encode = lambda *a, **kw: SentenceTransformer.encode(embedding_model, *a, **kw, show_progress_bar=False)

reranker_model_path = os.path.join(os.path.dirname(__file__), "models", "bge-reranker-base")
reranker_model = CrossEncoder(reranker_model_path)

def embed_text(text: str) -> list[float]:
    return embedding_model.encode(text, normalize_embeddings=True).tolist()

async def search_messages(session: AsyncSession, user_id: str, query: str, limit: int = 5):
    query_vec = embed_text(query)
    result = await session.execute(
        text("SELECT m.content, m.role, 1 - (m.embedding <=> cast(:qv as vector)) AS score "
            "FROM messages m JOIN conversations c ON m.conversation_id = c.id WHERE c.user_id = :uid AND embedding IS NOT NULL "
            "ORDER BY m.embedding <=> cast(:qv2 as vector) LIMIT :lim"),
        {"qv": str(query_vec), "qv2": str(query_vec), "uid": user_id, "lim": limit * 4}
    )
    candidates = [{"content": row.content, "role": row.role, "score": float(row.score)} for row in result]

    if candidates:
        pairs = [(query, c["content"]) for c in candidates]
        scores = reranker_model.predict(pairs)

        for i, c in enumerate(candidates):
            c["score"] = float(scores[i])
        candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:limit]
