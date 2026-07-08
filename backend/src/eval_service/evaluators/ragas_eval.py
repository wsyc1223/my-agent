import asyncio
import os
import sys
from .base import BaseEvaluator
from pydantic import SecretStr
from dotenv import load_dotenv
from src.rag import embed_text
from src.config import settings
from ragas.metrics._answer_relevance import AnswerRelevancy
from ragas.metrics._faithfulness import Faithfulness
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from ragas import EvaluationDataset, SingleTurnSample, evaluate


load_dotenv()
semaphore = asyncio.Semaphore(1)
# 工具方法
# 从 Langfuse trace 的 input/output 中提取纯文本
# LangChain CallbackHandler 记录的格式通常是 {"messages": [{"content": "...", ...}]}
def _extract_text(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # 格式: {"messages": [{"content": "..."}]}
        if "messages" in data:
            msgs = data["messages"]
            if isinstance(msgs, list) and msgs:
                last = msgs[-1]
                if isinstance(last, dict):
                    return last.get("content", str(last))
                return str(last)
        # 格式: {"content": "..."}
        if "content" in data:
            return data["content"]
        # 格式: {"output": "..."}
        if "output" in data:
            return str(data["output"])
        return str(data)
    if isinstance(data, list) and data:
        return _extract_text(data[-1])
    return str(data) if data else ""

# 封装本地的 BGE 向量化类，防止 Ragas 去请求收费的 OpenAI Embeddings
class LocalBgeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [embed_text(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return embed_text(text)

class RagasEvaluator(BaseEvaluator):
    async def evaluate(self, trace_data) -> dict[str, float]:
        """
        对模型的忠实度进行打分。
        """
        query = _extract_text(trace_data.input)
        answer = _extract_text(trace_data.output)

        # 获取工具检索的输出，提取作为 RAG 上下文
        contexts = []
        if hasattr(trace_data, "observations") and trace_data.observations:
            for obs in trace_data.observations:
                if obs.name in ["search_document_by_vector", "search_document_by_grep"]:
                    output_text = _extract_text(obs.output)
                    contexts.append(output_text)
        if not contexts:
            contexts = [""]

        # 组装 Ragas 测评集
        sample = SingleTurnSample(
            user_input=query,
            retrieved_contexts=contexts,
            response=answer
        )
        dataset = EvaluationDataset(samples=[sample])

        # 初始化 deepseek 作为Ragas 裁判大模型
        evaluator_llm = ChatOpenAI(
            model="deepseek-v4-flash",
            api_key=SecretStr(settings.DEEPSEEK_API_KEY),
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.0
        )
        evaluator_embeddings = LocalBgeEmbeddings()

        # 实例化 Ragas 指标
        # Faithfullness: 回答是否忠于检索到的上下文
        # AnswerRelevancy: 回答是否与用户问题相关
        # 注: ContextPrecision 需要 reference (标准答案)，线上测评无法提供，故不使用
        metrics = [
            Faithfulness(),
            AnswerRelevancy(strictness=1),
        ]

        # 获取最终评估结果
        async with semaphore:
            result = await asyncio.to_thread(
                evaluate,
                dataset=dataset,
                metrics=metrics,
                llm=evaluator_llm,
                embeddings=evaluator_embeddings
            )

        return {name: float(val) for name, val in result.items()}
