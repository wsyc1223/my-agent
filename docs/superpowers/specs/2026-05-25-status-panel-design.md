# 智能 Agent 状态面板重构设计方案规格书 (Design Specification)

本项目旨在彻底重构 LangChain 智能对话前端系统右侧的 Bento 状态控制台（`Reasoning Console`）。摆脱晦涩难读的英文底层日志，升级为易读、大气、富含科技美学的 **“智能状态引擎仪表盘”**，并深度适配系统的**“浅色简约液态玻璃（Light Liquid Glass）”**美学格调。

---

## 1. 核心设计原则

1. **信息高可视性 (High Visibility)**：用大号、高对比度的字重与大气的布局，让用户在 1 米外就能一眼看清 AI 当前处于什么工作状态。
2. **直观的色彩能量条 (Energy Spectrum & Breathing Rhythm)**：通过“绿、蓝、黄、灰”四种颜色的高精度液态呼吸律动，直观传达系统忙闲。
3. **极客液态玻璃美学 (Light Liquid Glass Aesthetic)**：
   - 使用透光率 `rgba(255, 255, 255, 0.45)` 的毛玻璃底座。
   - 融入超高模糊度的液态背景晕染（`backdrop-filter: blur(25px)` 与 top-right corner `radial-gradient` 的液态色彩绽放）。
   - 极窄能谱进度条与斜切流光反光层。

---

## 2. 状态映射与行为逻辑

我们将定义 4 个核心的系统级运行状态，并与 Pinia `chat` Store 的响应式状态完美双向绑定：

| 运行状态 | Pinia 状态绑定关系 | 律动条颜色与动画 | 视觉展示文字 |
| :--- | :--- | :--- | :--- |
| **A. 思考流式回答中** | `streaming.value && !toolRunning.value && !interrupted.value` | **翡翠绿 (Emerald Green)** 呼吸波 | **AI 正在思考并回答中...** |
| **B. 工具调用中** | `toolRunning.value` | **深海蓝 (Ocean Blue)** 呼吸波 | **AI 正在调用工具进行深度检索...** |
| **C. 等待安全确认** | `interrupted.value` | **警告黄 (Amber Yellow)** 双倍频呼吸 | **安全拦截：等待您批准执行敏感操作...** |
| **D. 系统就绪** | `!streaming.value && !toolRunning.value && !interrupted.value` | **太空灰 (Neutral Gray)** 静态线条 | **系统就绪，等待您的 Operator 指令** |

---

## 3. 具体修改计划

### 3.1 状态管理层重构：[src/stores/chat.ts](file:///home/wsyc1/projects/langchain/frontend/my-vue-project/src/stores/chat.ts)
- **目标**：在整个对话生命周期中精准且稳健地变异（Mutate）`toolRunning.value` 状态。
- **改动点**：
  1. `readStream` 函数：
     - 当捕获 `case 'tool_run'` 事件时，立即将 `toolRunning.value = true`。
     - 当流式吐字正式落地（第一 token 降临），或者捕获 `case 'text'`、`case 'done'`、`case 'error'`、`case 'interrupt'` 时，重置 `toolRunning.value = false`。
     - 在 `readStream` 整个流的 `finally` 块中加入兜底：`toolRunning.value = false`。
  2. `send` / `rejectTool` 函数：
     - 在接口请求结束或异常处理块中，确保重置 `toolRunning.value = false`。
  3. `approveTool` 函数：
     - 批准后，由于后端会立即在 resume 流中执行挂起的工具，所以在请求发送前，立即设置 `toolRunning.value = true`。

### 3.2 视图渲染层重构：[src/views/ChatView.vue](file:///home/wsyc1/projects/langchain/frontend/my-vue-project/src/views/ChatView.vue)
- **目标**：移除原有的终端日志行（`terminal-lines`），替换为大气的液态毛玻璃卡片结构。
- **改动点**：
  1. 在 `<aside class="observation-center">` 的 `.console-card` 中，移除原有的终端模拟界面。
  2. 嵌入全新的 Vue 动态状态绑定卡片，根据 `chat.streaming`、`chat.toolRunning` 和 `chat.interrupted` 的状态值动态切换对应的 class 与文字。
  3. 增加轻盈透明感的玻璃拉丝反光效果 `.glass-reflection`，以及极致精细的流线进度条。

---

## 4. 验证与回归测试计划

### 4.1 视觉效果回归 (Manual Verification)
- **启动/就绪**：打开页面，验证状态卡显示为淡雅灰色，文字显示：“系统就绪，等待您的 Operator 指令”。
- **提问/吐流**：向 AI 提问，流式响应期间，状态卡应转变为淡绿色呼吸渐变，文字显示：“AI 正在思考并回答中...”。
- **工具调用**：涉及天气等需要调用工具的提问，验证调用工具阶段状态卡是否转为亮蓝色呼吸渐变，文字显示：“AI 正在调用工具进行深度检索...”。
- **安全挂起**：涉及执行敏感操作被后端防火墙安全挂起时，验证状态卡是否自动切换为黄色警告呼吸，文字显示：“安全拦截：等待您批准执行敏感操作...”。

### 4.2 前端代码编译测试 (Automated Compile Validation)
- 运行 Vue 3 与 TypeScript 的类型检查编译，保证无类型冲突与未定义变量：
  ```bash
  npx vue-tsc --noEmit
  ```
