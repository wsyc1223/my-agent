import asyncio
from typing import Dict, AsyncGenerator
import json

class NotifierManager:
    def __init__(self):
        self.connections: Dict[str, set[asyncio.Queue]] = {}

    async def subscribe(self, conversation_id: str) -> AsyncGenerator[str, None]:
        """
        前端挂载长连接时调用此方法。
        产生一个异步生成器，只要连接不断开，就持续从当前会话的队列里拿数据往前端发送。
        """
        queue = asyncio.Queue()
        if conversation_id not in self.connections:
            self.connections[conversation_id] = set()
        self.connections[conversation_id].add(queue)

        try:
            yield f"data: {json.dumps({'type': 'ping'})}\n\n"

            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"

        except asyncio.CancelledError:
            # 当用户离开聊天界面、刷新浏览器或者关闭标签页导致长连接断开时，
            # asyncio 会自动向这个循环抛出 CancelledError
            pass
        finally:
            # 清理： 长连接关闭后，必须将相应的队列从广播集合里面删除，防止内存泄漏
            if conversation_id in self.connections:
                self.connections[conversation_id].discard(queue)
                if not self.connections[conversation_id]:
                    del self.connections[conversation_id]

    async def send_message(self, conversation_id: str, data: dict) -> None:
        """
        给后台异步任务调用，向该会话名下的所有活跃链接队列中广播投放数据包
        """
        if conversation_id in self.connections:
            queues = self.connections[conversation_id]
            for queue in queues:
                await queue.put(data)

notifier_manager = NotifierManager()
