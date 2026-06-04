#!/bin/bash
# 项目测试脚本

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "=== 项目测试 ==="

# 测试Python环境
cd "$BACKEND_DIR"
source .venv/bin/activate
echo "1. 测试Python导入..."
python -c "
import fastapi
import langchain
import langchain_openai
import nltk
print('✅ 所有核心包导入成功')
"

echo ""
echo "2. 测试环境变量..."
if [ -f ".env" ]; then
    echo "✅ .env文件存在"
    # 检查关键环境变量
    if grep -q "API_KEY" .env; then
        echo "✅ API密钥配置存在"
    fi
fi

echo ""
echo "3. 测试主应用..."
if python -c "from main import app; print('✅ 主应用导入成功')" 2>/dev/null; then
    echo "✅ 应用结构正常"
else
    echo "⚠️  应用导入可能有问题"
fi

echo ""
echo "4. 运行test.py..."
cd "$PROJECT_ROOT"
if [ -f "test.py" ]; then
    python test.py
else
    echo "⚠️  test.py不存在"
fi

echo ""
echo "=== 测试完成 ==="
