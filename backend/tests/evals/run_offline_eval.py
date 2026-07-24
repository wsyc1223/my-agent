import os
import sys
import asyncio
import json
from sqlalchemy import select
from pydantic import SecretStr
from dotenv import load_dotenv

# 将 backend 路径添加到 sys.path 以支持 src 模块导入
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_dir)

from src.db.session import AsyncSessionLocal
from src.db.model import User
from src.file_research.retriever import vector_search_chunks
from src.config import settings
from src.rag import embed_text
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics._answer_relevance import AnswerRelevancy
from ragas.metrics._faithfulness import Faithfulness

load_dotenv()

# 封装本地 BGE Embeddings, 防止 Ragas 调用第三方 Embedding 产生网络或费用开销
class LocalBgeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [embed_text(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return embed_text(text)

async def run_offline_baseline_eval():
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

    print(f"[INFO] Loaded {len(golden_set)} evaluation cases from golden_set.json.")

    # 初始化大模型与裁判模型
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=SecretStr(settings.DEEPSEEK_API_KEY),
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.0
    )
    
    evaluator_llm = ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=SecretStr(settings.DEEPSEEK_API_KEY),
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.0
    )
    
    evaluator_embeddings = LocalBgeEmbeddings()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("[ERROR] No user found in database. Please run generate_eval_data.py first.")
            return
        user_id = str(user.id)

        hits_at_1 = 0
        hits_at_3 = 0
        hits_at_5 = 0
        samples = []
        detailed_cases = []

        print("[INFO] Starting retrieval and LLM generation for baseline evaluation...")

        for idx, case in enumerate(golden_set):
            query = case["query"]
            target_chunk_id = int(case["source_chunk_id"])
            ground_truth = case.get("ground_truth_answer", "")

            # 1. 向量检索 (召回 Top 5)
            retrieved_chunks = await vector_search_chunks(
                session=session,
                query=query,
                user_id=user_id,
                limit=5
            )
            retrieved_ids = [int(c["chunk_id"]) for c in retrieved_chunks]
            contexts = [c["content"] for c in retrieved_chunks] if retrieved_chunks else [""]

            # 2. 计算 Recall 召回指标
            is_hit_1 = target_chunk_id in retrieved_ids[:1] if retrieved_ids else False
            is_hit_3 = target_chunk_id in retrieved_ids[:3] if len(retrieved_ids) >= 3 else False
            is_hit_5 = target_chunk_id in retrieved_ids

            if is_hit_1: hits_at_1 += 1
            if is_hit_3: hits_at_3 += 1
            if is_hit_5: hits_at_5 += 1

            # 3. 驱动大模型基于检索出的上下文生成回答
            context_str = "\n\n".join(contexts)
            prompt = (
                "你是一个专业助手。请仅根据给定的上下文回答用户的问题。\n"
                f"【上下文】:\n{context_str}\n\n"
                f"【用户问题】:\n{query}\n\n"
                "如果上下文无法推导，请直接回答'我不知道'。不要添加外部推测。"
            )

            try:
                response = await llm.ainvoke(prompt)
                generated_answer = response.content.strip()
            except Exception as e:
                print(f"[WARNING] LLM generation error on case #{idx+1}: {str(e)}")
                generated_answer = "ERROR_GENERATING_ANSWER"

            # 4. 构建 Ragas 评测样本
            samples.append(SingleTurnSample(
                user_input=query,
                retrieved_contexts=contexts,
                response=generated_answer,
                reference=ground_truth
            ))

            detailed_cases.append({
                "case_id": idx + 1,
                "query": query,
                "target_chunk_id": target_chunk_id,
                "retrieved_chunk_ids": retrieved_ids,
                "hit_in_top5": is_hit_5,
                "generated_answer": generated_answer,
                "reference_answer": ground_truth
            })

            print(f"[PROGRESS] Evaluated {idx + 1}/{len(golden_set)} cases (Recall Hit Top5: {is_hit_5})")
            await asyncio.sleep(0.5)

        total_cases = len(golden_set)
        recall_1 = hits_at_1 / total_cases
        recall_3 = hits_at_3 / total_cases
        recall_5 = hits_at_5 / total_cases

        # 5. 调用 Ragas 进行批量打分
        print("[INFO] Running Ragas evaluator for Faithfulness and Answer Relevancy...")
        dataset = EvaluationDataset(samples=samples)
        metrics = [
            Faithfulness(),
            AnswerRelevancy(strictness=1)
        ]

        ragas_scores = {}
        try:
            ragas_result = await asyncio.to_thread(
                evaluate,
                dataset=dataset,
                metrics=metrics,
                llm=evaluator_llm,
                embeddings=evaluator_embeddings
            )
            # 兼容 Ragas 0.4+ 的 EvaluationResult 对象: 使用 to_pandas() 获取每列平均分
            try:
                df = ragas_result.to_pandas()
                for col in df.columns:
                    if col in ["faithfulness", "answer_relevance", "answer_relevancy"]:
                        ragas_scores[col] = float(df[col].mean())
            except Exception as e_parse:
                print(f"[WARNING] DataFrame parse warning: {str(e_parse)}")
                ragas_scores = {"faithfulness": 0.0, "answer_relevance": 0.0}
        except Exception as e:
            print(f"[ERROR] Ragas evaluation failed: {str(e)}")
            ragas_scores = {"faithfulness": 0.0, "answer_relevance": 0.0}

        # 6. 汇总生成完整 V0 基线报告并持久化写入文件
        report_data = {
            "version": "V0_Baseline",
            "total_cases": total_cases,
            "retrieval_metrics": {
                "recall_at_1": round(recall_1, 4),
                "recall_at_3": round(recall_3, 4),
                "recall_at_5": round(recall_5, 4)
            },
            "ragas_metrics": ragas_scores,
            "detailed_cases": detailed_cases
        }

        output_report_path = os.path.join(evals_dir, "baseline_report.json")
        with open(output_report_path, "w", encoding="utf-8") as f_out:
            json.dump(report_data, f_out, ensure_ascii=False, indent=2)

        print("\n=================== V0 BASELINE EVALUATION REPORT ===================")
        print(f"Total Evaluated Cases : {total_cases}")
        print(f"Recall@1              : {recall_1:.2%}")
        print(f"Recall@3              : {recall_3:.2%}")
        print(f"Recall@5              : {recall_5:.2%}")
        for m_name, score_val in ragas_scores.items():
            print(f"Ragas {m_name:<16}: {score_val:.4f}")
        print("=====================================================================")
        print(f"[SUCCESS] Baseline report successfully saved to:\n  file://{output_report_path}\n")

if __name__ == "__main__":
    asyncio.run(run_offline_baseline_eval())
