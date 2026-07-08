from .base import BaseEvaluator

class ToolAccuracyEvaluator(BaseEvaluator):
    async def evaluate(self, trace_data) -> dict[str, float]:
        """
        工具准确率评估，判断是否调用了对应的工具。
        简单看有没有成功使用工具然后判断正确率，后续需要修改完善观测逻辑。
        """
        tool_calls_count = 0
        successful_count = 0

        if hasattr(trace_data, "observations") and trace_data.observations:
            for obs in trace_data.observations:
                if getattr(obs, "name", None) in ["search_document_by_vector", "search_document_by_grep", "search_web"]:
                    tool_calls_count += 1
                    output_text = str(getattr(obs, "output", "")).lower()

                    if "error" not in output_text:
                        successful_count += 1

        accuracy = successful_count / tool_calls_count if tool_calls_count > 0 else 1.0
        return {"agents_tool_call_successful_rate": accuracy}
