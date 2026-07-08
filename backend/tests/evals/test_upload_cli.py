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
        # 获取现有的 Mock 用户
        result = await session.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("[ERROR] No user found. Please run generate_eval_data.py first.")
            return
        user_id = str(user.id)
        token = create_access_token(user_id)
        print(f"[INFO] Generated JWT Token for user '{user.name}' (ID: {user_id})")

    # 创建一个用于上传测试的临时文件
    evals_dir = os.path.dirname(os.path.abspath(__file__))
    test_file_path = os.path.join(evals_dir, "test_doc.md")
    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write(
            "# Taskiq Redis 评测系统联调试验\n\n"
            "这是一个专用于测试 Taskiq 与 Redis 异步评估管线的测试文档。\n"
            "当我们通过 API 接口上传这个文件后，主后端应该首先接收该文件并开启后台线程进行分块解析与向量化入库。\n"
            "后台分块落库完成后，主服务应当向 Redis 队列发送一个 trace_id，触发 Taskiq Worker 异步消费，"
            "利用 Ragas 进行 Faithfulness、Answer Relevance 评估，并回传分数到 Langfuse 平台。"
        )
    
    print(f"[INFO] Created test file at: {test_file_path}")

    # 调用本地运行的 FastAPI 端口进行上传
    cmd = [
        "curl", "-s", "-X", "POST", "http://localhost:8000/file/upload",
        "-H", f"Authorization: Bearer {token}",
        "-F", f"file=@{test_file_path}"
    ]
    
    print("[INFO] Sending POST upload request via curl to http://localhost:8000/file/upload ...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    print(f"[RESPONSE] Server output:\n{res.stdout}")
    print("[INFO] Check your Taskiq Worker terminal and Langfuse platform to verify the evaluation task execution!")

if __name__ == "__main__":
    asyncio.run(main())
