from abc import ABC, abstractmethod

class BaseEvaluator(ABC):
    @abstractmethod
    async def evaluate(self, trace_data) -> dict[str, float]:
        """
        评估核心接口。
        输入: 从 Langfuse 拿到的 trace_data 详情。
        输出: 字典， 例如 {"metric_name": score_vlaue}
        """
        pass
