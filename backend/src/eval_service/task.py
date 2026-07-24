import os
import logging
import sys
import asyncio
from langfuse import Langfuse
from src.service.task_queue import redis_broker
from src.config import settings
from dotenv import load_dotenv

from src.eval_service.evaluators.ragas_eval import RagasEvaluator
from src.eval_service.evaluators.trajectory import TrajectoryEvaluator
from src.eval_service.evaluators.tool_accuracy import ToolAccuracyEvaluator

EVALUATORS = [
    RagasEvaluator(),
    TrajectoryEvaluator(),
    ToolAccuracyEvaluator()
]

load_dotenv()

logger = logging.getLogger(__name__)

# 定义 Tasking 异步测评任务
@redis_broker.task
async def evaluate_trace_task(trace_id: str, user_id: str) -> None:
    """
    异步评估任务: 根据 trace_id 从 Langfuse 拉取数据, 使用 Ragas 打分并回传
    """
    logger.info("eval_task_received", trace_id=trace_id)

    # 实例化 Langfuse 客户端 (会自动从环境变量读取 key)
    lf = Langfuse()

    try:
        trace_data = None
        max_attempts = 10
        # 网络瞬时错误的关键字，匹配超时、连接失败、SSL 等
        transient_keywords = ["timeout", "timed out", "connect", "ssl", "eof", "reset", "broken pipe"]

        # 从 Langfuse 中拉取数据 trace_data
        for attempt in range(max_attempts):
            wait_time = min(2 ** attempt, 30)
            try:
                trace_data = await asyncio.to_thread(lf.api.trace.get, trace_id)
                break
            except Exception as e:
                err_msg = str(e).lower()
                is_not_found = "404" in str(e) or "not found" in err_msg
                is_transient = any(kw in err_msg for kw in transient_keywords)

                if is_not_found:
                    logger.info("trace_not_ready", trace_id=trace_id, attempt=attempt+1)
                elif is_transient:
                    logger.warning("eval_transient_error", error=type(e).__name__, attempt=attempt+1)
                else:
                    raise e
                await asyncio.sleep(wait_time)

        if not trace_data:
            raise ValueError(f"Trace {trace_id} was not found on Langfuse after {max_attempts} attempts.")

        # 使用注册好的评估器逐个进行打分然后上传到 Langfuse
        all_scores = {}
        for evaluator in EVALUATORS:
            try:
                scores = await evaluator.evaluate(trace_data)
                all_scores.update(scores)
            except Exception as e:
                logger.error("evaluator_failed", evaluator=evaluator.__class__.__name__, error=str(e))

        for name, value in all_scores.items():
            lf.create_score(trace_id=trace_id, name=name, value=value)

    except Exception as e:
        logger.exception("ragas_eval_failed", trace_id=trace_id)
