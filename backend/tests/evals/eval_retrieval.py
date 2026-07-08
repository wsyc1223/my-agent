import os
import sys
import asyncio
import json
from sqlalchemy import select

# 将 backend 路径添加到 sys.path 以支持 src 导入
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_dir)

from src.db.session import AsyncSessionLocal
from src.db.model import User
from src.file_research.retriever import vector_search_chunks

async def run_evaluation():
    evals_dir = os.path.dirname(os.path.abspath(__file__))
    golden_set_path = os.path.join(evals_dir, "golden_set.json")
    
    if not os.path.exists(golden_set_path):
        print(f"[ERROR] Golden set not found at {golden_set_path}. Please run generate_eval_data.py first.")
        return

    with open(golden_set_path, "r", encoding="utf-8") as f:
        golden_set = json.load(f)

    if not golden_set:
        print("[ERROR] Golden set is empty.")
        return

    print(f"[INFO] Loaded {len(golden_set)} evaluation cases.")
    
    async with AsyncSessionLocal() as session:
        # 获取任意存在的用户（评测数据与该用户绑定）
        result = await session.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("[ERROR] No user found in database. Please run generate_eval_data.py first.")
            return
        user_id = str(user.id)

        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_5 = 0
        failures = []

        print("[INFO] Starting retrieval evaluation...")
        for idx, case in enumerate(golden_set):
            query = case["query"]
            target_chunk_id = int(case["source_chunk_id"])
            doc_name = case["source_doc_name"]

            # 调用向量检索
            retrieved_chunks = await vector_search_chunks(
                session=session,
                query=query,
                user_id=user_id,
                limit=5
            )

            retrieved_ids = [int(c["chunk_id"]) for c in retrieved_chunks]
            
            # 计算 Recall@K
            is_hit_5 = target_chunk_id in retrieved_ids
            is_hit_3 = target_chunk_id in retrieved_ids[:3]
            is_hit_1 = target_chunk_id in retrieved_ids[:1] if retrieved_ids else False

            if is_hit_1:
                hits_at_1 += 1
            if is_hit_3:
                hits_at_3 += 1
            if is_hit_5:
                hits_at_5 += 1
            else:
                failures.append({
                    "query": query,
                    "target_chunk_id": target_chunk_id,
                    "source_doc_name": doc_name,
                    "retrieved_ids": retrieved_ids,
                    "retrieved_filenames": [c["filename"] for c in retrieved_chunks]
                })

        total = len(golden_set)
        recall_at_1 = hits_at_1 / total
        recall_at_3 = hits_at_3 / total
        recall_at_5 = hits_at_5 / total

        print("\n================ EVALUATION REPORT ================")
        print(f"Total Test Cases: {total}")
        print(f"Recall@1: {recall_at_1:.2%} ({hits_at_1}/{total})")
        print(f"Recall@3: {recall_at_3:.2%} ({hits_at_3}/{total})")
        print(f"Recall@5: {recall_at_5:.2%} ({hits_at_5}/{total})")
        print("===================================================\n")

        if failures:
            print(f"[INFO] Analysis of {len(failures)} Retrieval Failures:")
            for f_idx, fail in enumerate(failures):
                print(f"\nFailure #{f_idx+1}:")
                print(f"  Query: {fail['query']}")
                print(f"  Source Doc: {fail['source_doc_name']} (Chunk ID: {fail['target_chunk_id']})")
                print(f"  Retrieved files: {fail['retrieved_filenames']} (Chunk IDs: {fail['retrieved_ids']})")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
