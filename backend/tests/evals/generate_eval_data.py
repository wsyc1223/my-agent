import os
import sys
import asyncio
import hashlib
import json
import random
from sqlalchemy import select

# 将 backend 路径添加到 sys.path 以支持 src 导入
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_dir)

# 预设的专用初始化测试语料（锁定在 tests/evals/fixtures/ 目录下）
FIXTURE_CORPUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "test_corpus.md")

async def ensure_test_user(session) -> "User":
    """获取或创建一个 Mock 测试用户"""
    from src.db.model import User
    
    result = await session.execute(select(User))
    user = result.scalars().first()
    if not user:
        user = User()
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"[INFO] Created mock user: {user.name} ({user.id})")
    else:
        print(f"[INFO] Found existing user: {user.name} ({user.id})")
    return user

async def seed_documents_if_empty(session, user_id: str):
    """安全增量追加模式：检查 dedicated test_corpus.md 是否已被索引，若未索引则解析入库"""
    from src.db.repository import FileDocumentRepository
    from src.service.file_research import process_file_in_background

    doc_repo = FileDocumentRepository(session)

    if not os.path.exists(FIXTURE_CORPUS_PATH):
        print(f"[ERROR] Dedicated test corpus not found at {FIXTURE_CORPUS_PATH}.")
        return

    doc_name = "test_corpus.md"
    print(f"[INFO] Checking dedicated test corpus: {FIXTURE_CORPUS_PATH}...")
    with open(FIXTURE_CORPUS_PATH, "rb") as f:
        file_data = f.read()

    sha256 = hashlib.sha256(file_data).hexdigest()
    text_content = file_data.decode("utf-8")

    # 检查当前文件是否已存在于数据库中，若存在则跳过
    existing = await doc_repo.get_by_sha256(user_id, sha256)
    if existing and existing.status == "indexed":
        print(f"[INFO] Document {doc_name} is already indexed in database. Skipping seed phase.")
        return
    elif existing:
        await doc_repo.delete(user_id, existing.id)
        await session.commit()

    print(f"[INFO] Appending new document {doc_name} (2.4W+ words) into database...")
    doc = await doc_repo.create(
        user_id=user_id,
        filename=doc_name,
        size_bytes=len(file_data),
        sha256=sha256,
        status="processing",
        full_content=text_content
    )
    await session.commit()
    await session.refresh(doc)

    print(f"[INFO] Indexing {doc_name} in background...")
    await process_file_in_background(doc.id, user_id, doc_name)
    print(f"[INFO] Document {doc_name} indexing completed successfully.")

async def generate_golden_set(session, user_id: str, limit_queries: int = 15):
    """采样 chunks 并调用 DeepSeek 接口生成 golden_set.json"""
    from src.db.model import FileChunk, FileDocument
    from src.config import settings
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    print("[INFO] Fetching candidate chunks for evaluation generation...")
    # 查询当前用户的所有 chunks
    result = await session.execute(
        select(FileChunk, FileDocument.filename)
        .join(FileDocument, FileChunk.document_id == FileDocument.id)
        .where(FileChunk.user_id == user_id)
    )
    rows = result.all()
    if not rows:
        print("[ERROR] No chunks found in database. Cannot generate evaluation dataset.")
        return

    # 过滤掉内容过短的 chunk (例如低于 100 字符)，确保生成质量
    candidates = [
        {
            "id": r[0].id,
            "document_id": str(r[0].document_id),
            "filename": r[1],
            "content": r[0].content
        }
        for r in rows
        if len(r[0].content.strip()) >= 100
    ]

    if len(candidates) < limit_queries:
        print(f"[WARNING] Candidate chunks count ({len(candidates)}) is less than target queries ({limit_queries}). Using all available chunks.")
        selected_candidates = candidates
    else:
        # 随机采样指定数量的 chunks
        selected_candidates = random.sample(candidates, limit_queries)

    print(f"[INFO] Initializing ChatOpenAI (DeepSeek) to generate {len(selected_candidates)} QA pairs...")
    llm = ChatOpenAI(
        model="deepseek-chat", # 使用 DeepSeek 对话模型进行生成
        api_key=SecretStr(settings.DEEPSEEK_API_KEY),
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.7
    )

    golden_set = []

    for idx, cand in enumerate(selected_candidates):
        print(f"[PROGRESS] Generating QA pair {idx+1}/{len(selected_candidates)} (Chunk ID: {cand['id']})")
        prompt = (
            "你是一个专业的测试工程师，专注于为检索增强生成(RAG)系统设计高质量的评估数据集。\n"
            "现在给你一段从文档中提取的文本片段（Chunk）：\n"
            "-------------------\n"
            f"来源文件: {cand['filename']}\n"
            f"片段内容:\n{cand['content']}\n"
            "-------------------\n"
            "请针对这段文本，生成一个用户在实际使用中可能会问到的“高质量中文提问”(query)，"
            "并结合给定的文本片段写出对应的“标准参考答案”(ground_truth_answer)。\n\n"
            "要求：\n"
            "1. 提问必须自然、符合真实人类语言习惯，且可以直接使用上述给定的文本片段进行完整、准确地回答。严禁生成无法从文本中推导的问题。\n"
            "2. 标准参考答案必须完全忠实于给定的文本片段，不得夹杂或补充任何外部事实、知识或个人推论（防止产生幻觉）。\n"
            "3. 你的输出必须是一个合法的 JSON 字符串，包含且仅包含键 'query' 和 'ground_truth_answer'，不要包含任何 Markdown 格式前缀（例如 ```json）或任何额外的解释文字。\n"
            "JSON 格式示例如下：\n"
            "{\n"
            '  "query": "生成的问题",\n'
            '  "ground_truth_answer": "生成的答案"\n'
            "}"
        )

        try:
            response = await llm.ainvoke(prompt)
            raw_content = response.content.strip()
            
            # 清理可能残留的 markdown 标记
            if raw_content.startswith("```json"):
                raw_content = raw_content[7:]
            if raw_content.endswith("```"):
                raw_content = raw_content[:-3]
            raw_content = raw_content.strip()

            qa_data = json.loads(raw_content)
            
            golden_set.append({
                "query": qa_data["query"],
                "ground_truth_context": cand["content"],
                "ground_truth_answer": qa_data["ground_truth_answer"],
                "source_doc_name": cand["filename"],
                "source_doc_id": cand["document_id"],
                "source_chunk_id": cand["id"]
            })
        except Exception as e:
            print(f"[WARNING] Failed to generate QA for Chunk {cand['id']}. Error: {str(e)}")
            continue

    # 保存文件
    evals_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(evals_dir, "golden_set.json")
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(golden_set, f, ensure_ascii=False, indent=2)

    print(f"[SUCCESS] Successfully generated {len(golden_set)} evaluation cases.")
    print(f"[SUCCESS] Saved dataset to: {output_path}")

async def main():
    from src.db.session import AsyncSessionLocal
    
    async with AsyncSessionLocal() as session:
        # 1. 确保 Mock 用户存在
        user = await ensure_test_user(session)
        user_id = str(user.id)

        # 2. 如果数据库为空，从项目根目录读取本地文档进行数据初始化（Seed）
        await seed_documents_if_empty(session, user_id)

        # 3. 采样并生成黄金评测集
        await generate_golden_set(session, user_id, limit_queries=15)

if __name__ == "__main__":
    asyncio.run(main())
