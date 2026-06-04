<script setup lang="ts">
import { ref, nextTick, watch, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css' // 亮色清爽代码主题

const chat = useChatStore()
const input = ref('')
const msgEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)

// 渲染 Markdown 的核心计算函数
function renderMarkdown(content: string) {
  if (!content) return ''
  try {
    return marked.parse(content) as string
  } catch (e) {
    return content
  }
}

// 高级原生 DOM 注入：为代码块生成极客复制按钮与语言角标
function injectCodeBlockFeatures() {
  nextTick(() => {
    const pres = document.querySelectorAll('.markdown-body pre')
    pres.forEach((pre) => {
      // 避免重复注入
      if (pre.querySelector('.copy-btn-3d')) return
      
      const element = pre as HTMLElement
      element.style.position = 'relative'
      
      // 创建复制按钮
      const copyBtn = document.createElement('button')
      copyBtn.className = 'copy-btn-3d'
      copyBtn.innerHTML = 'Copy'
      copyBtn.setAttribute('title', '复制代码')
      
      const codeEl = pre.querySelector('code')
      const textToCopy = codeEl ? codeEl.innerText : ''
      
      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(textToCopy)
          copyBtn.innerHTML = '✓ Copied'
          copyBtn.classList.add('copied')
          setTimeout(() => {
            copyBtn.innerHTML = 'Copy'
            copyBtn.classList.remove('copied')
          }, 2000)
        } catch (err) {
          copyBtn.innerHTML = 'Error'
        }
      })
      
      pre.appendChild(copyBtn)
      
      // 提取语言标识
      if (codeEl) {
        const classes = Array.from(codeEl.classList)
        const langClass = classes.find(c => c.startsWith('language-'))
        if (langClass) {
          const lang = langClass.replace('language-', '').toUpperCase()
          const badge = document.createElement('span')
          badge.className = 'lang-badge-3d'
          badge.innerHTML = lang
          pre.appendChild(badge)
        }
      }
    })
  })
}

// 动态高亮所有 Markdown 代码块并注入交互按钮
function highlightCode() {
  nextTick(() => {
    const codes = document.querySelectorAll('.markdown-body pre code')
    codes.forEach((block) => {
      const element = block as HTMLElement
      if (chat.streaming) {
        hljs.highlightElement(element)
      } else if (!element.dataset.highlighted) {
        hljs.highlightElement(element)
        element.dataset.highlighted = 'true'
      }
    })
    injectCodeBlockFeatures()
  })
}

// 自动滚动并渲染代码高亮与交互
watch(() => chat.messages.length, () => {
  nextTick(() => msgEl.value?.scrollTo({ top: msgEl.value.scrollHeight, behavior: 'smooth' }))
  highlightCode()
})

watch(() => chat.messages, () => {
  highlightCode()
  // 当 AI 处于 streaming (流式输出) 状态时，随着新字输出自动平滑向下滚动以提升体验
  if (chat.streaming) {
    nextTick(() => msgEl.value?.scrollTo({ top: msgEl.value.scrollHeight, behavior: 'auto' }))
  }
}, { deep: true })

watch(() => chat.interrupted, () => {
  nextTick(() => msgEl.value?.scrollTo({ top: msgEl.value.scrollHeight, behavior: 'smooth' }))
})

// textarea 高度自适应
function adjustHeight() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

watch(input, () => {
  nextTick(adjustHeight)
})

async function send() {
  const text = input.value.trim()
  if (!text || chat.streaming || chat.interrupted) return
  input.value = ''
  if (textareaEl.value) {
    textareaEl.value.style.height = '44px' // 重置高度
  }
  await chat.send(text)
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

onMounted(() => {
  highlightCode()
})
</script>

<template>
  <main class="main">
    <!-- 极富系统仪式感的顶部 Header -->
    <header class="chat-header">
      <div class="header-left">
        <span class="thread-status-dot" :class="{ active: chat.streaming }"></span>
        <span class="header-title">
          {{ chat.currentId
            ? (chat.conversations.find(c => c.id === chat.currentId)?.title || 'Active Session')
            : 'New Session' }}
        </span>
      </div>
      <div class="header-right">
        <span v-if="chat.streaming" class="streaming-label">
          <span class="spinner"></span>
          Agent 正在决策运行...
        </span>
      </div>
    </header>

    <!-- 响应式多板块 Bento Grid 工作区 -->
    <div class="workspace-bento">
      
      <!-- 主聊天对话流交互板块 (中栏) -->
      <div class="chat-area">
        <div ref="msgEl" class="messages-container">
          <!-- 载入状态 -->
          <div v-if="chat.loading" class="loading-state-3d">
            <div class="orbit-spinner"></div>
            <span>正在载入操作系统数据栈...</span>
          </div>
          
          <!-- 欢迎面板 (极高水准 bento 引导卡片) -->
          <div v-else-if="chat.messages.length === 0" class="welcome-hub-3d">
            <div class="welcome-logo-3d">⌥</div>
            <h1 class="welcome-title">Agentic OS</h1>
            <p class="welcome-subtitle">搭载 LangChain 混合决策链的高级 Operator 人机协作终端</p>
            
            <div class="preset-cards-grid">
              <div class="preset-card" @click="input = '分析当前前端代码的重构亮点，给出专业的建议。'">
                <span class="card-icon">🎨</span>
                <h3>UI 极致美学分析</h3>
                <p>全面评估并获取系统在光影、交互及流光边框上的进化建议</p>
              </div>
              <div class="preset-card" @click="input = '帮我用 Python 写一个支持多线程的爬虫脚本。'">
                <span class="card-icon">⚡</span>
                <h3>极客沙箱代码运行</h3>
                <p>直接调用安全沙箱运行多线程 Python 代码，呈现完整输出日志</p>
              </div>
            </div>
          </div>

          <!-- 消息历史流 -->
          <div class="message-list" v-else>
            <div
              v-for="(m, i) in chat.messages"
              :key="i"
              class="msg-wrapper"
              :class="[m.role, { streaming: i === chat.messages.length - 1 && chat.streaming }]"
            >
              <div class="msg-bubble-3d">
                <div class="msg-body markdown-body" v-html="renderMarkdown(m.content || (chat.streaming && i === chat.messages.length - 1 ? '...' : ''))"></div>
                <span v-if="i === chat.messages.length - 1 && chat.streaming" class="cursor-glow" />
              </div>
            </div>
          </div>

          <!-- 人机协同高阶拦截审批卡片 (Cyberpunk Shimmer Firewall Alert) -->
          <div v-if="chat.interrupted" class="approval-overlay-3d">
            <div class="approval-card-3d">
              <div class="shimmer-border"></div>
              <div class="approval-header-3d">
                <div class="alert-icon-3d">🚨</div>
                <div class="approval-header-text">
                  <h3>ACTION INTERCEPTED</h3>
                  <p>Agent 正在请求执行高权限敏感工具，需要 Operator 安全确认</p>
                </div>
              </div>
              
              <div class="approval-details-inset">
                <div class="detail-row">
                  <span class="detail-lbl">Thread Node ID:</span>
                  <code class="detail-val">{{ chat.interruptThreadId }}</code>
                </div>
                <div class="detail-row">
                  <span class="detail-lbl">Safety Shield:</span>
                  <span class="detail-val-badge">Human-in-the-loop Active</span>
                </div>
              </div>

              <div class="approval-actions-3d">
                <button class="btn-approve-3d" :disabled="chat.approving" @click="chat.approveTool()">
                  <span class="pulse-indicator-success"></span>
                  {{ chat.approving ? '⚡ Processing...' : '✓ Approve & Resume' }}
                </button>
                <button class="btn-reject-3d" :disabled="chat.approving" @click="chat.rejectTool()">
                  Deny Execution
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部胶囊式立体输入控制台 -->
        <div class="input-area-3d">
          <div class="input-wrapper-3d">
            <div class="input-row-3d">
              <textarea
                ref="textareaEl"
                v-model="input"
                rows="1"
                placeholder="输入 Operator 指令以启动会话..."
                :disabled="chat.streaming || chat.interrupted"
                @keydown="handleKeyDown"
              />
              <button 
                class="send-btn-3d" 
                :disabled="chat.streaming || chat.interrupted || !input.trim()" 
                @click="send"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
                </svg>
              </button>
            </div>
            <div class="input-footer-bar">
              <div class="footer-shortcuts">
                <span class="shortcut-tag">Enter 发送</span>
                <span class="shortcut-tag">Shift + Enter 换行</span>
              </div>
              <div class="node-status-tag">
                <span class="node-dot"></span>
                Sandbox Shield Active
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Agent 观测状态中心仪表盘 (右侧大屏专属 Bento 格) -->
      <aside class="observation-center">
        <!-- 便当格 1: 工具激活箱 -->
        <div class="bento-card toolbox-card">
          <h3 class="bento-card-title">🔌 Active Toolbox</h3>
          <p class="bento-card-subtitle">当前内核已挂载的自主操作工具箱</p>
          <div class="tools-grid">
            <div class="tool-item active" title="命令行终端执行工具">
              <span class="tool-icon">📟</span>
              <span class="tool-name">Shell Run</span>
              <span class="tool-status-dot"></span>
            </div>
            <div class="tool-item active" title="隔离代码沙箱运行环境">
              <span class="tool-icon">🐍</span>
              <span class="tool-name">Py Sandbox</span>
              <span class="tool-status-dot"></span>
            </div>
            <div class="tool-item active" title="联网实时信息检索器">
              <span class="tool-icon">🌐</span>
              <span class="tool-name">Web Search</span>
              <span class="tool-status-dot"></span>
            </div>
            <div class="tool-item active" title="本地系统文件管理器">
              <span class="tool-icon">📁</span>
              <span class="tool-name">File System</span>
              <span class="tool-status-dot"></span>
            </div>
          </div>
        </div>

        <!-- 便当格 2: 智能 Agent 状态面板 (浅色简约液态玻璃) -->
        <div class="bento-card console-card" :class="[
          chat.streaming && !chat.toolRunning && !chat.interrupted ? 'b-streaming' : '',
          chat.toolRunning ? 'b-tools' : '',
          chat.interrupted ? 'b-warning' : '',
          !chat.streaming && !chat.toolRunning && !chat.interrupted ? 'b-ready' : ''
        ]">
          <div class="top-line-b" :class="[
            chat.streaming && !chat.toolRunning && !chat.interrupted ? 'line-green-b' : '',
            chat.toolRunning ? 'line-blue-b' : '',
            chat.interrupted ? 'line-yellow-b' : '',
            !chat.streaming && !chat.toolRunning && !chat.interrupted ? 'line-gray-b' : ''
          ]"></div>
          <div class="glass-reflection"></div>
          
          <h3 class="bento-card-title">🤖 Agent Status Engine</h3>
          <p class="bento-card-subtitle">系统运行状态与 Operator 控制仪表盘</p>
          
          <div class="status-panel-body">
            <!-- 状态 A：思考流式回答中 -->
            <div v-if="chat.streaming && !chat.toolRunning && !chat.interrupted" class="status-content">
              <span class="preview-badge-b tag-green-b">
                <span class="pulse-dot dot-green"></span>
                思考中
              </span>
              <div class="status-label-b font-dark">AI 正在思考并回答中...</div>
              <div class="status-sub-b">Streaming Response...</div>
            </div>

            <!-- 状态 B：正在调用工具 -->
            <div v-else-if="chat.toolRunning" class="status-content">
              <span class="preview-badge-b tag-blue-b">
                <span class="pulse-dot dot-blue"></span>
                调用工具
              </span>
              <div class="status-label-b font-dark">AI 正在调用工具进行深度检索...</div>
              <div class="status-sub-b">Executing Tasks & Sandboxes...</div>
            </div>

            <!-- 状态 C：安全拦截等待确认 -->
            <div v-else-if="chat.interrupted" class="status-content">
              <span class="preview-badge-b tag-yellow-b">
                <span class="pulse-dot dot-yellow"></span>
                安全拦截
              </span>
              <div class="status-label-b font-dark">安全拦截：等待您批准敏感操作...</div>
              <div class="status-sub-b">Awaiting Operator Approval...</div>
            </div>

            <!-- 状态 D：就绪 -->
            <div v-else class="status-content">
              <span class="preview-badge-b tag-gray-b">
                <span class="dot-static"></span>
                系统就绪
              </span>
              <div class="status-label-b font-gray-b">系统就绪，等待您的 Operator 指令</div>
              <div class="status-sub-b">Kernel Idle & Ready</div>
            </div>
          </div>
        </div>

        <!-- 便当格 3: 系统安全仪表盘 -->
        <div class="bento-card status-card">
          <h3 class="bento-card-title">🛡️ Node Dashboard</h3>
          <p class="bento-card-subtitle">节点防御与运行指标参数</p>
          <div class="status-rows">
            <div class="status-row">
              <span class="status-lbl">Shield Node</span>
              <span class="status-val text-success">L3 Sandbox</span>
            </div>
            <div class="status-row">
              <span class="status-lbl">Approval Guard</span>
              <span class="status-val text-primary">Active</span>
            </div>
            <div class="status-row">
              <span class="status-lbl">RTT Latency</span>
              <span class="status-val text-secondary">32ms</span>
            </div>
            <div class="status-row">
              <span class="status-lbl">Kernel Core</span>
              <span class="status-val text-secondary font-mono">Gemini 3.5</span>
            </div>
          </div>
        </div>
      </aside>
      
    </div>
  </main>
</template>

<style scoped>
.main { 
  flex: 1; 
  display: flex; 
  flex-direction: column; 
  min-width: 0; 
  min-height: 0; /* 防止子元素高度撑爆外层 flex 容器，允许其跟随 App 高度收缩 */
  background: transparent; 
}

/* 极致系统级 Header */
.chat-header {
  padding: 16px 24px; 
  border-bottom: 1px solid var(--border-color);
  display: flex; 
  align-items: center; 
  justify-content: space-between;
  min-height: 60px; 
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  transition: var(--transition-smooth);
}

html.dark .chat-header {
  background: rgba(15, 15, 17, 0.35);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.thread-status-dot {
  width: 6px; height: 6px;
  background: var(--text-muted);
  border-radius: 50%;
  transition: var(--transition-smooth);
}

.thread-status-dot.active {
  background: var(--primary);
  box-shadow: 0 0 10px var(--primary-glow);
}

.header-title { 
  font-size: 14.5px; 
  font-weight: 700; 
  color: var(--text-primary); 
  letter-spacing: 0.5px;
}

.streaming-label {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.spinner {
  width: 10px; height: 10px;
  border: 1.5px solid rgba(0, 0, 0, 0.1);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

html.dark .spinner {
  border: 1.5px solid rgba(255, 255, 255, 0.1);
  border-top-color: var(--primary);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Bento Grid 工作区底座 */
.workspace-bento {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 280px; /* 大屏下：对话流占主体，右侧为观测中心 */
  overflow: hidden;
  transition: var(--transition-smooth);
}

@media (max-width: 992px) {
  .workspace-bento {
    grid-template-columns: 1fr; /* 中小屏幕下自动隐藏/折叠右侧观测中心 */
  }
  .observation-center {
    display: none !important;
  }
}

/* 中栏对话交互区 */
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  min-height: 0; /* 阻止内容撑爆 Grid 单格高度限制，保证能够触发内部滚动 */
}

/* 消息流体容器 */
.messages-container {
  flex: 1; 
  overflow-y: auto; 
  padding: 32px 24px;
  display: flex; 
  flex-direction: column; 
  position: relative;
  min-height: 0; /* 允许消息容器自由收缩以激活滚动 */
  scrollbar-width: thin; /* 兼容 Firefox 的细滚动条 */
  scrollbar-color: rgba(0, 0, 0, 0.15) transparent; /* Firefox 亮色模式滚动条颜色 */
}

/* 兼容 Firefox 暗黑模式下的滚动条 */
html.dark .messages-container {
  scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
}

/* 3D Orbit 加载态 */
.loading-state-3d {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-secondary);
  font-size: 14px;
}

.orbit-spinner {
  width: 32px; height: 32px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: var(--primary);
  border-bottom-color: var(--primary);
  animation: spin 1.2s cubic-bezier(0.5, 0, 0.5, 1) infinite;
}

/* 3D 欢迎引导控制中心 */
.welcome-hub-3d {
  flex: 1; 
  display: flex; 
  flex-direction: column; 
  align-items: center;
  justify-content: center; 
  max-width: 600px;
  margin: 0 auto;
  text-align: center;
  padding-bottom: 40px;
}

.welcome-logo-3d {
  font-size: 40px; 
  color: var(--primary); 
  width: 72px; height: 72px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  box-shadow: var(--shadow-lift);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
  text-shadow: 0 0 10px var(--primary-glow);
}

.welcome-title { 
  font-size: 26px; 
  font-weight: 700; 
  color: var(--text-primary); 
  letter-spacing: -0.5px;
  margin-bottom: 10px;
}

.welcome-subtitle { 
  font-size: 14px; 
  color: var(--text-secondary); 
  margin-bottom: 32px;
  line-height: 1.5;
}

.preset-cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  width: 100%;
}

@media (max-width: 600px) {
  .preset-cards-grid { grid-template-columns: 1fr; }
}

.preset-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 20px;
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow-lift);
  transition: var(--transition-smooth);
}

.preset-card:hover {
  background: var(--bg-card-hover);
  border-color: rgba(255, 255, 255, 0.4);
  box-shadow: var(--shadow-card);
  transform: translateY(-2px);
}

html.dark .preset-card:hover {
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 8px 24px rgba(139, 92, 246, 0.15);
}

.card-icon {
  font-size: 20px;
  margin-bottom: 10px;
  display: block;
}

.preset-card h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.preset-card p {
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
}

/* 消息卡片：Claude 级极致居中与科技宽敞呼吸感 */
.message-list {
  max-width: 780px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.msg-wrapper { 
  display: flex; 
  max-width: 85%;
  align-items: flex-start;
  animation: popIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes popIn {
  from { opacity: 0; transform: scale(0.97) translateY(12px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.msg-wrapper.user { 
  align-self: flex-end; 
}

.msg-wrapper.assistant {
  align-self: flex-start;
  width: 100%;
  max-width: 92%;
}

/* 消息气泡 */
.msg-bubble-3d {
  display: flex;
  flex-direction: column;
  padding: 14px 20px;
  border-radius: var(--radius-md);
  position: relative;
  transition: var(--transition-smooth);
}

/* 3D 用户气泡 */
.msg-wrapper.user .msg-bubble-3d {
  background: var(--bg-user-msg);
  color: hsl(142, 50%, 15%);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.02), 
              inset 0 1px 0 rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(0, 0, 0, 0.03);
  border-bottom-right-radius: 2px;
}

html.dark .msg-wrapper.user .msg-bubble-3d {
  color: #f4f4f5;
  border: 1px solid rgba(139, 92, 246, 0.15);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2),
              inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

/* Claude 式通透无边界 AI 消息卡片 */
.msg-wrapper.assistant .msg-bubble-3d {
  background: rgba(255, 255, 255, 0.25); 
  color: var(--text-primary);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.01);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-left: 3px solid var(--primary);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: 14px 20px;
  backdrop-filter: blur(5px);
}

html.dark .msg-wrapper.assistant .msg-bubble-3d {
  background: rgba(26, 26, 29, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-left: 3px solid var(--primary);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.msg-body {
  font-size: 15px;
  line-height: 1.7;
  word-break: break-word;
}

/* 消息流发光微特效 */
.msg-wrapper.streaming .msg-bubble-3d {
  border-left: 3px solid var(--primary);
  box-shadow: 0 0 12px var(--primary-glow);
}

.cursor-glow::after { 
  content: "▊"; 
  animation: flash-glow 0.8s infinite; 
  color: var(--primary); 
  margin-left: 2px; 
  font-size: 12px; 
}

@keyframes flash-glow { 50% { opacity: 0; } }

/* 🛡️ 晶莹防线：2026极客安全拦截卡片 (Premium Glass Alert) */
.approval-overlay-3d {
  display: flex;
  justify-content: center;
  margin: 24px 0;
  animation: alertPop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes alertPop {
  from { opacity: 0; transform: scale(0.92) translateY(15px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.approval-card-3d {
  position: relative;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid rgba(239, 68, 68, 0.15); /* 红色警示边框 */
  border-radius: var(--radius-lg);
  padding: 24px;
  max-width: 520px;
  width: 100%;
  box-shadow: 0 15px 40px rgba(239, 68, 68, 0.03),
              inset 0 1px 0 rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(25px);
  overflow: hidden;
}

html.dark .approval-card-3d {
  background: rgba(20, 10, 15, 0.6); /* 带有暗红折光的碳黑 */
  border: 1px solid rgba(239, 68, 68, 0.25);
  box-shadow: 0 15px 45px rgba(0, 0, 0, 0.4),
              0 0 25px rgba(239, 68, 68, 0.05);
}

/* 脉冲式警告流光背景 */
.shimmer-border {
  position: absolute;
  top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, transparent, #ef4444, #f59e0b, transparent);
  background-size: 200% 100%;
  animation: shimmer-flow 3s infinite linear;
}

@keyframes shimmer-flow {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.approval-header-3d {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.alert-icon-3d {
  font-size: 24px;
  animation: pulse-red 1.5s infinite;
}

@keyframes pulse-red {
  0% { transform: scale(1); filter: drop-shadow(0 0 0px rgba(239, 68, 68, 0)); }
  50% { transform: scale(1.1); filter: drop-shadow(0 0 8px rgba(239, 68, 68, 0.5)); }
  100% { transform: scale(1); filter: drop-shadow(0 0 0px rgba(239, 68, 68, 0)); }
}

.approval-header-text h3 {
  font-size: 14px;
  font-weight: 800;
  color: #dc2626;
  margin-bottom: 4px;
  letter-spacing: 1px;
}

html.dark .approval-header-text h3 {
  color: #ef4444;
}

.approval-header-text p {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
}

.approval-details-inset {
  background: rgba(0, 0, 0, 0.02);
  box-shadow: var(--shadow-inset);
  border: 1px solid rgba(0, 0, 0, 0.01);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  margin-bottom: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

html.dark .approval-details-inset {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.01);
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.detail-lbl {
  color: var(--text-secondary);
}

.detail-val {
  font-family: 'Fira Code', monospace;
  color: var(--text-primary);
  font-weight: 600;
}

.detail-val-badge {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.15);
  color: #ef4444;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 700;
}

/* 拟物化 3D 动作键 */
.approval-actions-3d {
  display: flex;
  gap: 12px;
}

.btn-approve-3d, .btn-reject-3d {
  flex: 1;
  padding: 12px 18px;
  border-radius: var(--radius-md);
  font-size: 13.5px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  transition: var(--transition-smooth);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

/* 拟物化生机/极客绿键 */
.btn-approve-3d {
  background: linear-gradient(180deg, #10b981 0%, #047857 100%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2),
              inset 0 1px 1px rgba(255, 255, 255, 0.2);
}

.btn-approve-3d:hover:not(:disabled) {
  background: linear-gradient(180deg, #34d399 0%, #047857 100%);
  box-shadow: 0 6px 16px rgba(16, 185, 129, 0.3);
  transform: translateY(-1px);
}

.btn-approve-3d:active {
  transform: translateY(1px);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2);
}

.btn-approve-3d:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* 3D 拟物灰暗拒绝键 */
.btn-reject-3d {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.8) 0%, rgba(240, 240, 235, 0.8) 100%);
  border: 1px solid rgba(0, 0, 0, 0.05);
  color: var(--text-secondary);
  box-shadow: var(--shadow-lift);
}

html.dark .btn-reject-3d {
  background: linear-gradient(180deg, rgba(40, 40, 45, 0.8) 0%, rgba(25, 25, 30, 0.8) 100%);
  border: 1px solid rgba(255, 255, 255, 0.04);
  color: var(--text-secondary);
}

.btn-reject-3d:hover:not(:disabled) {
  background: linear-gradient(180deg, #ef4444 0%, #b91c1c 100%);
  border-color: rgba(255, 255, 255, 0.1);
  color: #ffffff;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.25);
  transform: translateY(-1px);
}

.btn-reject-3d:active {
  transform: translateY(1px);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.1);
}

/* 底部胶囊输入控制台 */
.input-area-3d {
  padding: 12px 24px 32px;
  display: flex;
  justify-content: center;
}

.input-wrapper-3d {
  max-width: 780px;
  width: 100%;
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(25px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 20px;
  padding: 10px 10px 8px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.03), 
              0 1px 1px rgba(0, 0, 0, 0.01);
  display: flex;
  flex-direction: column;
  transition: var(--transition-smooth);
}

html.dark .input-wrapper-3d {
  background: rgba(22, 22, 24, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
}

.input-row-3d {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-row-3d textarea {
  flex: 1;
  padding: 10px 14px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 15px;
  outline: none;
  font-family: inherit;
  resize: none;
  line-height: 1.6;
  height: 44px;
  max-height: 180px;
}

.input-row-3d textarea::placeholder {
  color: var(--text-muted);
}

/* 3D 高发光发送按钮 */
.send-btn-3d {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: linear-gradient(145deg, var(--primary), var(--primary-glow));
  color: #ffffff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(16, 122, 50, 0.1);
  transition: var(--transition-smooth);
  flex-shrink: 0;
  margin-bottom: 4px;
  margin-right: 4px;
}

.send-btn-3d:hover:not(:disabled) {
  box-shadow: 0 0 15px var(--primary-glow);
  transform: scale(1.03);
}

html.dark .send-btn-3d:hover:not(:disabled) {
  box-shadow: 0 0 15px rgba(139, 92, 246, 0.4);
}

.send-btn-3d:active {
  transform: scale(0.97);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.15);
}

.send-btn-3d:disabled {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-muted);
  border-color: transparent;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
}

html.dark .send-btn-3d:disabled {
  background: rgba(255, 255, 255, 0.02);
}

/* 输入栏辅助控制区 */
.input-footer-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px 4px;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
  margin-top: 8px;
}

html.dark .input-footer-bar {
  border-top: 1px solid rgba(255, 255, 255, 0.02);
}

.footer-shortcuts {
  display: flex;
  gap: 8px;
}

.shortcut-tag {
  font-size: 10.5px;
  color: var(--text-secondary);
  background: rgba(0, 0, 0, 0.03);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(0, 0, 0, 0.01);
}

html.dark .shortcut-tag {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.01);
}

.node-status-tag {
  font-size: 10.5px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}

.node-dot {
  width: 5px; height: 5px;
  background: var(--success);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--success);
}

/* ============================================================ */
/* 💻 Agent 观测中心 (Bento Grid Dashboard in Right Column) */
/* ============================================================ */
.observation-center {
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(15px);
  border-left: 1px solid var(--border-color);
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  transition: var(--transition-smooth);
}

html.dark .observation-center {
  background: rgba(12, 12, 14, 0.45);
}

/* 统一便当卡 */
.bento-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-lift);
  transition: var(--transition-smooth);
}

.bento-card:hover {
  background: var(--bg-card-hover);
  border-color: rgba(255, 255, 255, 0.4);
  box-shadow: var(--shadow-card);
}

html.dark .bento-card:hover {
  border-color: rgba(255, 255, 255, 0.05);
}

.bento-card-title {
  font-size: 12px;
  font-weight: 800;
  color: var(--text-primary);
  letter-spacing: 0.8px;
  margin-bottom: 3px;
  text-transform: uppercase;
}

.bento-card-subtitle {
  font-size: 10px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

/* 卡片 1: 工具激活列表 */
.tools-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.tool-item {
  background: rgba(0, 0, 0, 0.02);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  position: relative;
  transition: var(--transition-smooth);
}

html.dark .tool-item {
  background: rgba(255, 255, 255, 0.01);
}

.tool-item.active {
  background: rgba(255, 255, 255, 0.8);
  border-color: rgba(255, 255, 255, 0.9);
}

html.dark .tool-item.active {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.03);
}

.tool-item:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-lift);
}

.tool-icon { font-size: 16px; }
.tool-name { font-size: 9.5px; font-weight: 600; color: var(--text-secondary); }

.tool-status-dot {
  position: absolute;
  top: 6px; right: 6px;
  width: 4px; height: 4px;
  background: var(--success);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--success);
}

/* 卡片 2: 智能 Agent 状态仪表盘 (浅色简约液态玻璃) */
.console-card {
  position: relative;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.45) !important;
  backdrop-filter: blur(25px) !important;
  -webkit-backdrop-filter: blur(25px) !important;
  border: 1px solid rgba(255, 255, 255, 0.6) !important;
  box-shadow: 
    0 10px 30px rgba(0, 0, 0, 0.03),
    0 1px 2px rgba(0, 0, 0, 0.01),
    inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
}

.console-card:hover {
  background: rgba(255, 255, 255, 0.55) !important;
  border-color: rgba(255, 255, 255, 0.8) !important;
  transform: translateY(-2px);
  box-shadow: 
    0 15px 35px rgba(0, 0, 0, 0.06),
    0 0 1px rgba(0, 0, 0, 0.05) !important;
}

/* 贯穿顶部的能谱流光微细线条 */
.top-line-b {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 4px;
  background-size: 200% 100%;
  z-index: 10;
}

/* 渐变流体晕染背景 */
.b-streaming {
  background: radial-gradient(circle at top right, rgba(16, 185, 129, 0.12) 0%, rgba(255, 255, 255, 0.45) 75%) !important;
}
.line-green-b {
  background: linear-gradient(90deg, #10b981, #34d399, #10b981);
  animation: barFlow 2s linear infinite;
}
.tag-green-b {
  background: rgba(16, 185, 129, 0.08);
  color: #065f46;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.b-tools {
  background: radial-gradient(circle at top right, rgba(96, 165, 250, 0.12) 0%, rgba(255, 255, 255, 0.45) 75%) !important;
}
.line-blue-b {
  background: linear-gradient(90deg, #3b82f6, #60a5fa, #3b82f6);
  animation: barFlow 2s linear infinite;
}
.tag-blue-b {
  background: rgba(59, 130, 246, 0.08);
  color: #1e3a8a;
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.b-warning {
  background: radial-gradient(circle at top right, rgba(245, 158, 11, 0.12) 0%, rgba(255, 255, 255, 0.45) 75%) !important;
}
.line-yellow-b {
  background: linear-gradient(90deg, #f59e0b, #fbbf24, #f59e0b);
  animation: barFlow 1.5s linear infinite;
}
.tag-yellow-b {
  background: rgba(245, 158, 11, 0.08);
  color: #78350f;
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.b-ready {
  background: rgba(255, 255, 255, 0.45) !important;
}
.line-gray-b {
  background: #9ca3af;
}
.tag-gray-b {
  background: rgba(107, 114, 128, 0.05);
  color: #4b5563;
  border: 1px solid rgba(107, 114, 128, 0.15);
}

/* 反光流拉丝效果 */
.glass-reflection {
  position: absolute;
  top: 0; left: -150%;
  width: 200%; height: 100%;
  background: linear-gradient(105deg, transparent 30%, rgba(255, 255, 255, 0.3) 40%, transparent 50%);
  transform: skewX(-25deg);
  pointer-events: none;
  animation: shineReflect 6s ease-in-out infinite;
}

@keyframes shineReflect {
  0% { left: -150%; }
  20%, 100% { left: 150%; }
}

/* 呼吸红绿黄指示圆点 */
.pulse-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}
.dot-green { background: #10b981; animation: dotBreathe 1.5s ease-in-out infinite; box-shadow: 0 0 6px #10b981; }
.dot-blue { background: #3b82f6; animation: dotBreathe 1.5s ease-in-out infinite; box-shadow: 0 0 6px #3b82f6; }
.dot-yellow { background: #f59e0b; animation: dotBreathe 1.2s ease-in-out infinite; box-shadow: 0 0 6px #f59e0b; }

.dot-static {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
  background: #9ca3af;
}

.preview-badge-b {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
  margin-bottom: 14px;
  letter-spacing: 0.5px;
  display: inline-flex;
  align-items: center;
}

.status-label-b {
  font-size: 16px;
  font-weight: 800;
  line-height: 1.5;
  margin-bottom: 12px;
}

.font-dark {
  color: #1f2937;
}

.font-gray-b {
  color: #4b5563;
}

.status-sub-b {
  font-size: 10.5px;
  font-family: 'Fira Code', 'Courier New', Courier, monospace;
  color: #6b7280;
  letter-spacing: 0.2px;
}

@keyframes barFlow {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

@keyframes dotBreathe {
  0%, 100% { opacity: 0.4; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}

/* 卡片 3: 安全仪表盘 */
.status-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.02);
}

html.dark .status-row {
  border-bottom: 1px solid rgba(255, 255, 255, 0.02);
}

.status-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.status-lbl {
  color: var(--text-secondary);
  font-weight: 500;
}

.status-val {
  font-weight: 700;
}

.text-success { color: #10b981; }
</style>

<style>
/* ============================================================ */
/* 📝 Markdown 全局排版进化 (2026 前沿极客科技排版体系) */
/* ============================================================ */
.markdown-body {
  color: var(--text-primary);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; /* 回归无衬线科技感 */
  font-size: 14.5px;
  line-height: 1.7;
}

.markdown-body p {
  margin-bottom: 12px;
  line-height: 1.7;
  color: var(--text-primary);
}

.markdown-body p:last-child {
  margin-bottom: 0;
}

.markdown-body strong {
  font-weight: 700;
  color: var(--text-primary);
}

.markdown-body ul, .markdown-body ol {
  margin: 8px 0 14px 20px;
}

.markdown-body li {
  margin-bottom: 6px;
  line-height: 1.65;
  color: var(--text-primary);
}

/* 极致 3D 极客 Markdown 代码框 (Bento Dark code block) */
.markdown-body pre {
  background: #0d0e12 !important; /* 纯深灰极客质感背景 */
  border: 1px solid rgba(255, 255, 255, 0.04) !important;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.8);
  border-radius: var(--radius-md) !important;
  padding: 38px 16px 16px !important; /* 顶部加宽以绝对定位按钮 */
  overflow-x: auto;
  margin: 14px 0 !important;
}

.markdown-body code {
  font-family: 'Fira Code', 'Courier New', Courier, monospace;
  font-size: 13px;
  color: var(--primary); /* 与主题色高亮一致 */
  font-weight: 500;
}

.markdown-body pre code {
  color: #e4e4e7 !important; /* 代码高亮文字呈白色 */
  background: transparent;
  padding: 0;
}

/* 普通内联 code */
.markdown-body :not(pre) > code {
  background: rgba(0, 0, 0, 0.03);
  border: 1px solid rgba(0, 0, 0, 0.02);
  color: var(--primary);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  font-weight: 600;
}

html.dark .markdown-body :not(pre) > code {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.01);
}

/* ============================================================ */
/* ⚡ 复制按钮与语言角标的 CSS 动态匹配 (3D High Glass Glassmorphism) */
/* ============================================================ */
.copy-btn-3d {
  position: absolute;
  top: 8px; right: 8px;
  z-index: 10;
  padding: 4px 8px;
  font-size: 10px;
  font-weight: 700;
  font-family: 'Inter', sans-serif;
  color: #a1a1aa;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.03);
  border-radius: var(--radius-sm);
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  backdrop-filter: blur(5px);
  transition: all 0.2s ease;
}

.copy-btn-3d:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.08);
}

.copy-btn-3d.copied {
  color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.2);
}

.lang-badge-3d {
  position: absolute;
  top: 9px; left: 12px;
  z-index: 10;
  font-size: 9px;
  font-weight: 800;
  font-family: 'Fira Code', monospace;
  color: #52525b;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
</style>
