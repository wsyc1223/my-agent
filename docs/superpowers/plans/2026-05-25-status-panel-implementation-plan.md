# 智能 Agent 状态面板重构实施计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端右侧 Bento 观测台中的 `Reasoning Console` 升级为大气、直白的“浅色简约液态玻璃风格”状态引擎仪表盘，精准展示“思考中、调用工具、安全拦截、系统就绪”四种核心状态。

**Architecture:** 
1. 在 Pinia `chat.ts` 中管理状态：精准且稳健地捕获 SSE 数据流中不同事件阶段并变异 `toolRunning.value` 的生命周期。
2. 在 `ChatView.vue` 视图层中，移除英文终端模拟容器，嵌入全新带有 HSL 浅色能谱渐变背景、流光细条和呼吸圆点的高级液态毛玻璃面板，绑定响应式状态。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Vanilla Scoped CSS (Glassmorphism & Radial Mesh Gradients).

---

## 计划分解任务 (Bite-Sized Tasks)

### 任务 1: 状态管理层 `toolRunning` 响应式重构

**Files:**
- Modify: `frontend/my-vue-project/src/stores/chat.ts`

- [ ] **步骤 1.1: 重构 `readStream` 流式状态捕获**
  - **定位文件**：`frontend/my-vue-project/src/stores/chat.ts` 的 `readStream` 函数 (约 56 行 - 176 行)
  - **修改内容**：
    1. 在 `while (true)` 外部使用 `try...finally` 结构包裹，确保连接中断或异常退出时强制把 `toolRunning.value` 归零。
    2. 在 `case 'tool_run'` 块中，设置 `toolRunning.value = true`。
    3. 在 `case 'text'` 块中，当 `!hasTextStarted` 且开始接收大模型字符时，设置 `toolRunning.value = false`。
    4. 在 `case 'interrupt'`、`case 'done'`、`case 'error'` 块中，全部重置 `toolRunning.value = false`。
  
  ```typescript
  // 核心改动细节：
  async function readStream(res: Response, msgIndex: number) {
    console.log(`[readStream] 开始读取统一标准化 JSON 数据流，目标消息索引: ${msgIndex}`);
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let pending = ''
    let animating = false
    let hasTextStarted = false

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)

          try {
            const event = JSON.parse(payload)
            if (!event || typeof event !== 'object') continue

            switch (event.type) {
              case 'conversation_id':
                currentId.value = event.conversation_id
                break
              case 'tool_run':
                console.log('[readStream] 捕获工具运行信令，工具列表:', event.tool_names);
                toolRunning.value = true // 🌟 设置工具正在运行
                const toolMsg = messages.value[msgIndex]
                if (toolMsg) {
                  const displayNames = event.tool_names ? event.tool_names.join(', ') : 'tool'
                  toolMsg.content = `⚙️ **[Operator System]** AI 正在执行工具任务: \`${displayNames}\` ...\n\n`
                  messages.value = [...messages.value]
                }
                break
              case 'text':
                if (event.content) {
                  const msg = messages.value[msgIndex]
                  if (!hasTextStarted) {
                    hasTextStarted = true
                    toolRunning.value = false // 🌟 首字降临，停止工具运行状态
                    if (msg && msg.content.startsWith('⚙️')) {
                      msg.content = ''
                      messages.value = [...messages.value]
                    }
                  }
                  push(event.content.replace(/\\n/g, '\n'))
                }
                break
              case 'interrupt':
                console.log('[readStream] 拦截到高权限中断请求，挂起流并开启审批');
                interrupted.value = true
                toolRunning.value = false // 🌟 中断挂起，停止工具状态
                interruptThreadId.value = event.thread_id
                interruptConvId.value = event.conversation_id
                return
              case 'done':
                console.log('[readStream] 收到统一流结束信号 done');
                toolRunning.value = false // 🌟 流结束，重置工具状态
                break
              case 'error':
                console.error('[readStream] 收到后端异常信令:', event.message);
                toolRunning.value = false // 🌟 错误退出，重置工具状态
                const errMsg = messages.value[msgIndex]
                if (errMsg) errMsg.content = `错误: ${event.message}`
                break
            }
          } catch (err) {
            console.error('[readStream] JSON 信令解析失败，payload:', payload, '错误:', err)
          }
        }
      }
    } finally {
      toolRunning.value = false // 🌟 强力安全兜底
    }
  }
  ```

- [ ] **步骤 1.2: 重构发送与审批动作中的状态重置**
  - **定位文件**：`frontend/my-vue-project/src/stores/chat.ts` 的 `send`、`approveTool` 和 `rejectTool` 函数
  - **修改内容**：
    1. 在 `send` 的 `catch` 块中加入 `toolRunning.value = false`。
    2. 在 `approveTool` 触发请求前，显式把 `toolRunning.value = true`。
    3. 在 `rejectTool` 开始时，重置 `toolRunning.value = false`。
  
  ```typescript
  // 核心改动细节：
  async function send(text: string) {
    if (!text.trim() || streaming.value) return
    messages.value.push({ role: 'user', content: text })
    streaming.value = true
    interrupted.value = false
    toolRunning.value = false // 🌟 初始发送时重置状态
    ...
  }

  async function approveTool() {
    if (!interruptThreadId.value) return
    approving.value = true
    interrupted.value = false
    toolRunning.value = true // 🌟 确认运行，工具状态立刻激活

    ...
  }
  ```

---

### 任务 2: 视图渲染层 `ChatView.vue` 升级

**Files:**
- Modify: `frontend/my-vue-project/src/views/ChatView.vue`

- [ ] **步骤 2.1: 升级卡片 HTML 模板**
  - **定位文件**：`frontend/my-vue-project/src/views/ChatView.vue` 中的 `observation-center` 卡片 2 (约 313 行 - 331 行)
  - **修改内容**：移除原有的终端模拟界面，替换为动态绑定流体样式的轻盈卡片结构。
  
  ```html
  <!-- 修改后结构： -->
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
        <div class="status-label-b font-dark">安全拦截：等待您批准执行敏感操作...</div>
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
  ```

- [ ] **步骤 2.2: 补充浅色液态玻璃 Scoped CSS 样式**
  - **定位文件**：`frontend/my-vue-project/src/views/ChatView.vue` 的 `<style scoped>` 尾部 (1230 行左右)
  - **修改内容**：添加我们在 3.0 版视觉伴侣中设计通过的极具质感、优雅的流体毛玻璃、反光闪烁和指示点动效样式。
  
  ```css
  /* ============ 浅色简约液态玻璃状态面板样式 ============ */
  .console-card {
    position: relative;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.45) !important;
    backdrop-filter: blur(25px) !important;
    -webkit-backdrop-filter: blur(25px) !important;
    border: 1px solid rgba(255, 255, 255, 0.6) !important;
    transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1) !important;
  }

  .console-card:hover {
    background: rgba(255, 255, 255, 0.55) !important;
    border-color: rgba(255, 255, 255, 0.8) !important;
  }

  /* 贯穿顶部的进度细线 */
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
  ```

---

## 验证与发布测试步骤

- [ ] **任务 3: 代码类型编译与发布回归测试**
  - **运行指令**：
    ```bash
    npx vue-tsc --noEmit
    ```
  - **预期表现**：控制台 0 error，编译完美通过。
  - **交互流程测试**：
    1. 刷新系统页面，检查控制台显示为系统就绪状态（太空灰指标线 + 太空灰静态点 + 文字“系统就绪”）。
    2. 发送提问，思考流式响应开启，验证是否立刻转变为翡翠绿呼吸渐变与翡翠绿闪烁呼吸点。
    3. 工具调用发生时，验证是否流畅转变为深海蓝流光渐变与深海蓝闪烁呼吸点。
    4. 审批事件触发时，验证是否立刻转变为警告黄大片晕染，并流畅提醒审批。
