#!/bin/bash
# LangChain项目开发启动脚本

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend/my-vue-project"

echo "=== LangChain项目开发环境启动 ==="
echo "项目根目录: $PROJECT_ROOT"

# 加载WSL环境变量
if [ -f "$PROJECT_ROOT/.env.wsl" ]; then
    source "$PROJECT_ROOT/.env.wsl"
    echo "已加载WSL环境变量"
fi

# 启动后端
echo ""
echo "启动后端服务..."
cd "$BACKEND_DIR"
source .venv/bin/activate
echo "Python环境: $(python --version)"
echo "启动FastAPI服务 (端口: ${API_PORT:-8000})..."
uvicorn main:app --reload --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000} &

BACKEND_PID=$!
echo "后端进程PID: $BACKEND_PID"

# 启动前端
echo ""
echo "启动前端服务..."
cd "$FRONTEND_DIR"
echo "启动Vue开发服务器 (端口: ${FRONTEND_PORT:-5173})..."
npm run dev &

FRONTEND_PID=$!
echo "前端进程PID: $FRONTEND_PID"

echo ""
echo "=== 服务已启动 ==="
echo "后端API: http://localhost:${API_PORT:-8000}"
echo "前端应用: http://localhost:${FRONTEND_PORT:-5173}"
echo "后端文档: http://localhost:${API_PORT:-8000}/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待中断信号
trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT
wait
