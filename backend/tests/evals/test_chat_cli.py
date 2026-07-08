import os
import sys
import asyncio
import subprocess
from sqlalchemy import select

# 将 backend 路径添加到 sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(backend_dir)

async def main():
    from src.db.session import AsyncSessionLocal
    from src.db.model import User
    from src.utils.security import create_access_token

    async with AsyncSessionLocal() as session:
        # 1. 获取现有的 Mock 用户 'test1'
        result = await session.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("[ERROR] No user found. Please run generate_eval_data.py first.")
            return
        user_id = str(user.id)
        token = create_access_token(user_id)
        print(f"[INFO] Generated JWT Token for user '{user.name}' (ID: {user_id})")

    # 2. 构造聊天消息
    question = "请问这个项目的评估体系（Evals）是用什么实现的，起到了什么作用？"
    print(f"[INFO] Prepared Question: '{question}'")

    # 3. 使用 curl 调用本地运行的 FastAPI 对话流接口
    cmd = [
        "curl", "-N", "-X", "POST", "http://localhost:8000/agent/chat/stream",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", f'{{"message": "{question}", "conversation_id": null, "global_memory": false}}'
    ]
    
    print("[INFO] Initiating streaming chat request via curl...")
    # -N 参数保证 curl 能够流式输出数据，不缓存
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    print("\n--- STREAMING START ---")
    for line in process.stdout:
        print(line, end="")
    print("--- STREAMING END ---\n")
    
    print("[INFO] Chat stream finished.")
    print("[INFO] Please check your Taskiq Worker terminal to view the asynchronous Ragas evaluation execution!")

if __name__ == "__main__":
    asyncio.run(main())
