from .base import BaseEvaluator

class TrajectoryEvaluator(BaseEvaluator):
    async def evaluate(self, trace_data) -> dict[str, float]:
        """
        统计 trace_data.observations 的长度，判断是否陷入了循环
        如果说 length <= 8 打 1.0, 否则打 0.0
        """
        score = 1.0

        if hasattr(trace_data, "observations"):
            obs_len = len(trace_data.observations)
            if obs_len <= 8:
                score = 1.0
            else:
                score = 0.0
        return {"agent_trajectory_efficiency": score}
