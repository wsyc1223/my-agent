#!/bin/bash
# LangChain项目环境配置脚本

set -e

echo "=== LangChain项目环境配置 ==="
echo "此脚本将配置WSL环境变量和别名"

# 配置bashrc
BASHRC="$HOME/.bashrc"
ENV_MARKER="# LangChain项目环境配置"

if ! grep -q "$ENV_MARKER" "$BASHRC"; then
    echo ""
    echo "配置bashrc环境变量..."
    cat >> "$BASHRC" << 'BASHRC_EOF'

# LangChain项目环境配置
export LANGCHAIN_PROJECT="$HOME/projects/langchain"
export PYTHONPATH="$LANGCHAIN_PROJECT/backend:$PYTHONPATH"

# 项目别名
alias lc="cd \$LANGCHAIN_PROJECT"
alias lc-backend="cd \$LANGCHAIN_PROJECT/backend && source .venv/bin/activate"
alias lc-frontend="cd \$LANGCHAIN_PROJECT/frontend"
alias lc-start="./start-dev.sh"
alias lc-test="./test-project.sh"

echo "LangChain项目环境已加载。使用 'lc' 进入项目目录"
BASHRC_EOF
    echo "✅ bashrc配置完成"
else
    echo "✅ 环境配置已存在"
fi

# 创建便捷脚本
echo ""
echo "创建便捷脚本..."
cat > "$HOME/bin/lc-activate" << 'SCRIPT_EOF'
#!/bin/bash
# 激活LangChain项目环境
cd "$HOME/projects/langchain/backend"
source .venv/bin/activate
echo "LangChain后端环境已激活"
echo "项目目录: $(pwd)"
echo "Python: $(python --version)"
SCRIPT_EOF

chmod +x "$HOME/bin/lc-activate"

# 确保bin目录在PATH中
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "$BASHRC"
    echo "✅ 添加 ~/bin 到PATH"
fi

echo ""
echo "=== 配置完成 ==="
echo "请运行以下命令使配置生效:"
echo "source ~/.bashrc"
echo ""
echo "可用命令:"
echo "  lc          - 进入项目目录"
echo "  lc-backend  - 进入后端并激活虚拟环境"
echo "  lc-frontend - 进入前端目录"
echo "  lc-start    - 启动开发服务器"
echo "  lc-test     - 运行项目测试"
echo "  lc-activate - 激活后端环境"
