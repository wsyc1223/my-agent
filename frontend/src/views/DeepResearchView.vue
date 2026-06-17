<script setup lang="ts">
import { ref, onMounted, nextTick, watch, computed } from 'vue'
import { useResearchStore } from '@/stores/research'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css' // 代码语法高亮
import ResearchSidebar from '@/components/ResearchSidebar.vue'
import { apiUrl, getAuthHeaders } from '@/services/api'

const research = useResearchStore()
const input = ref('')
const msgEl = ref<HTMLElement | null>(null)
const reportEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)

// 标签页与文件展示逻辑
interface Tab {
  id: string
  title: string
  content: string
  type: 'report' | 'file'
}

const tabs = ref<Tab[]>([])
const activeTabId = ref<string>('')
const uploading = ref(false)
const attachedFiles = ref<{ id: string; name: string; type: string; showFull?: boolean }[]>([])

const showReport = computed(() => tabs.value.length > 0)
const activeTab = computed(() => tabs.value.find(t => t.id === activeTabId.value))
const activeTabContent = computed(() => activeTab.value?.content || '')

const lastAssistantMsgIndex = computed(() => {
  for (let i = research.messages.length - 1; i >= 0; i--) {
    const msg = research.messages[i]
    if (msg && msg.role === 'assistant') {
      return i
    }
  }
  return -1
})

// 搜索检索逻辑
const searchQuery = ref('')
const searchActive = ref(false)
const searchMatchCount = ref(0)
const isSearchConfirmed = ref(false)
let currentHighlightIndex = 0

// 渲染 Markdown
function renderMarkdown(content: string) {
  if (!content) return ''
  try {
    const rawHtml = marked.parse(content) as string
    return DOMPurify.sanitize(rawHtml)
  } catch (e) {
    return content
  }
}

// 动态高亮代码块
function highlightCode() {
  nextTick(() => {
    const codes = document.querySelectorAll('.markdown-body pre code')
    codes.forEach((block) => {
      const element = block as HTMLElement
      if (!element.dataset.highlighted) {
        hljs.highlightElement(element)
        element.dataset.highlighted = 'true'
      }
    })
  })
}

// 文本高亮检索匹配核心逻辑
function executeSearchHighlight() {
  if (!reportEl.value) return
  
  // 清除上次高亮
  const marks = reportEl.value.querySelectorAll('mark.search-highlight')
  marks.forEach(mark => {
    const parent = mark.parentNode
    if (parent) {
      parent.replaceChild(document.createTextNode(mark.textContent || ''), mark)
      parent.normalize()
    }
  })
  searchMatchCount.value = 0

  if (!searchQuery.value.trim()) return

  const query = searchQuery.value.trim().toLowerCase()
  const walker = document.createTreeWalker(reportEl.value, NodeFilter.SHOW_TEXT, null)
  const nodesToReplace: { node: Text, matches: { start: number, end: number }[] }[] = []

  let node
  while (node = walker.nextNode() as Text) {
    const text = node.nodeValue?.toLowerCase() || ''
    let startIndex = 0
    let index
    const matches = []
    while ((index = text.indexOf(query, startIndex)) > -1) {
      matches.push({ start: index, end: index + query.length })
      startIndex = index + query.length
    }
    if (matches.length > 0) {
      nodesToReplace.push({ node, matches })
    }
  }

  let totalMatches = 0
  for (const { node, matches } of nodesToReplace) {
    const textContent = node.nodeValue || ''
    const fragment = document.createDocumentFragment()
    let lastEnd = 0

    for (const match of matches) {
      if (match.start > lastEnd) {
        fragment.appendChild(document.createTextNode(textContent.slice(lastEnd, match.start)))
      }
      const mark = document.createElement('mark')
      mark.className = 'search-highlight'
      mark.id = `search-match-${totalMatches}`
      mark.textContent = textContent.slice(match.start, match.end)
      fragment.appendChild(mark)
      lastEnd = match.end
      totalMatches++
    }
    if (lastEnd < textContent.length) {
      fragment.appendChild(document.createTextNode(textContent.slice(lastEnd)))
    }
    node.parentNode?.replaceChild(fragment, node)
  }
  
  searchMatchCount.value = totalMatches
  currentHighlightIndex = 0
  if (isSearchConfirmed.value) {
    scrollToMatch()
  }
}

function scrollToMatch() {
  if (searchMatchCount.value === 0) return
  document.querySelectorAll('mark.search-highlight.current').forEach(m => m.classList.remove('current'))
  
  const currentMark = document.getElementById(`search-match-${currentHighlightIndex}`)
  if (currentMark) {
    currentMark.classList.add('current')
    currentMark.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

function nextMatch() {
  if (searchMatchCount.value > 0) {
    currentHighlightIndex = (currentHighlightIndex + 1) % searchMatchCount.value
    scrollToMatch()
  }
}

function handleSearchEnter() {
  isSearchConfirmed.value = true
  nextMatch()
}

function toggleSearch() {
  searchActive.value = !searchActive.value
  if (!searchActive.value) {
    searchQuery.value = ''
    isSearchConfirmed.value = false
    executeSearchHighlight()
  } else {
    nextTick(() => searchInput.value?.focus())
  }
}

// 自动滚动聊天与高亮
watch(() => research.messages, () => {
  highlightCode()
  if (research.streaming) {
    nextTick(() => msgEl.value?.scrollTo({ top: msgEl.value.scrollHeight, behavior: 'auto' }))
  }
}, { deep: true })

// 自动更新报告标签页内容
watch(() => research.reportContent, (newVal) => {
  highlightCode()
  if (newVal) {
    const existing = tabs.value.find(t => t.id === 'report')
    if (existing) {
      existing.content = newVal
    } else {
      tabs.value.push({
        id: 'report',
        title: '📝 深度调研报告.md',
        content: newVal,
        type: 'report'
      })
    }
  }
})

// 监听会话变更
watch(() => research.currentId, () => {
  tabs.value = []
  activeTabId.value = ''
  searchQuery.value = ''
  searchActive.value = false
  if (research.reportContent) {
    tabs.value.push({
      id: 'report',
      title: '📝 深度调研报告.md',
      content: research.reportContent,
      type: 'report'
    })
  }
})

// 实时搜索高亮
let searchTimeout: any
watch(searchQuery, () => {
  isSearchConfirmed.value = false
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    executeSearchHighlight()
  }, 300)
})

// 自适应文本框高度
function adjustHeight() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

watch(input, () => nextTick(adjustHeight))

// 发送指令
async function send() {
  const text = input.value.trim()
  if (!text || research.streaming) return
  const filesToSend = [...attachedFiles.value]
  input.value = ''
  attachedFiles.value = []
  if (textareaEl.value) textareaEl.value.style.height = '44px'
  await research.send(text, filesToSend)
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

// 刻度条导航
const scaleTicks = computed(() => {
  const turns = []
  for (let i = 0; i < research.messages.length; i += 2) {
    turns.push({
      index: i,
      userMsg: research.messages[i]?.content || '...',
    })
  }
  return turns
})

function jumpToTurn(index: number) {
  const elements = msgEl.value?.querySelectorAll('.msg-wrapper')
  if (elements && elements[index]) {
    elements[index].scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// 文件上传
function triggerFileUpload() {
  fileInput.value?.click()
}

async function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return
  
  const file = files[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  
  const headers: HeadersInit = {}
  const authHeaders = getAuthHeaders()
  if (authHeaders.Authorization) {
    headers['Authorization'] = authHeaders.Authorization
  }

  uploading.value = true
  try {
    const res = await fetch(apiUrl('/file/upload'), {
      method: 'POST',
      headers,
      body: formData
    })
    
    if (res.status === 401) {
      window.location.href = '/login'
      return
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    attachedFiles.value.push({
      id: data.document_id,
      name: data.filename,
      type: data.filename.split('.').pop() || 'unknown',
      showFull: false
    })
  } catch (err) {
    console.error('[file upload] error:', err)
    alert('文件上传失败，请重试')
  } finally {
    uploading.value = false
    target.value = ''
  }
}

function removeAttachedFile(idx: number) {
  attachedFiles.value.splice(idx, 1)
}

// 点击文件或点击报告卡片时在右侧展现
async function openFileReport(fileId: string) {
  const existing = tabs.value.find(t => t.id === fileId)
  if (existing) {
    activeTabId.value = fileId
    return
  }

  try {
    const res = await fetch(apiUrl(`/file/${fileId}`), {
      headers: getAuthHeaders()
    })
    if (res.status === 401) {
      window.location.href = '/login'
      return
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    
    tabs.value.push({
      id: data.id,
      title: `📄 ${data.filename}`,
      content: data.full_content || '该文件没有解析出文本内容。',
      type: 'file'
    })
    activeTabId.value = data.id
  } catch (err) {
    console.error('[openFileReport] error:', err)
    alert('无法打开文件内容')
  }
}

// 显式打开报告标签页并展现在右侧
function openReportTab() {
  const existing = tabs.value.find(t => t.id === 'report')
  if (existing) {
    existing.content = research.reportContent
  } else {
    tabs.value.push({
      id: 'report',
      title: '📝 深度调研报告.md',
      content: research.reportContent,
      type: 'report'
    })
  }
  activeTabId.value = 'report'
}

function closeTab(id: string, e: Event) {
  e.stopPropagation()
  const idx = tabs.value.findIndex(t => t.id === id)
  if (idx !== -1) {
    tabs.value.splice(idx, 1)
    if (activeTabId.value === id) {
      if (tabs.value.length > 0) {
        const lastTab = tabs.value[tabs.value.length - 1]
        if (lastTab) {
          activeTabId.value = lastTab.id
        }
      } else {
        activeTabId.value = ''
      }
    }
  }
}

function truncateName(name: string) {
  if (name.length <= 16) return name
  const ext = name.split('.').pop() || ''
  const base = name.slice(0, 10)
  return `${base}...${ext ? '.' + ext : ''}`
}

onMounted(async () => {
  await research.fetchSessions()
  if (research.reportContent) {
    tabs.value.push({
      id: 'report',
      title: '📝 深度调研报告.md',
      content: research.reportContent,
      type: 'report'
    })
  }
})
</script>

<template>
  <div class="research-layout" :class="{ 'has-report': showReport }">
    
    <!-- 消息历史侧边栏 -->
    <div class="sidebar-col card-wrapper">
      <ResearchSidebar />
    </div>

    <!-- 核心对话列 -->
    <div class="chat-col card-wrapper" :class="{ 'is-empty': research.messages.length === 0 }">
      <div class="chat-header">
        <div class="header-title-area">
          <span class="status-pulse" :class="{ pulsing: research.streaming || research.toolRunning }"></span>
          <h2>深度研究</h2>
        </div>
        <button class="back-btn" @click="$router.push('/')">
          返回普通对话
        </button>
      </div>

      <div class="chat-content-flex" :class="{ 'is-centered': research.messages.length === 0 }">
        <!-- 消息流区域 -->
        <div v-if="research.messages.length > 0" class="chat-messages" ref="msgEl">
          <div v-for="(m, i) in research.messages" :key="i" class="msg-wrapper" :class="m.role">
            <div class="msg-bubble markdown-body" v-html="renderMarkdown(m.content)"></div>
            
            <!-- 用户上传附件的展示 -->
            <div v-if="m.files && m.files.length > 0" class="message-files">
              <div 
                v-for="file in m.files" 
                :key="file.id" 
                class="file-attachment-card"
                @click="openFileReport(file.id)"
                :title="file.name"
              >
                <div class="file-icon-wrapper">
                  <span class="file-badge">{{ file.type.toUpperCase() }}</span>
                </div>
                <div class="file-details">
                  <span class="file-name">{{ truncateName(file.name) }}</span>
                </div>
              </div>
            </div>

            <!-- AI生成调研报告的查看卡片 -->
            <div v-if="m.role === 'assistant' && research.reportContent && i === lastAssistantMsgIndex" class="message-files">
              <div 
                class="file-attachment-card report-card-btn"
                @click="openReportTab"
                title="查看深度报告"
              >
                <div class="file-icon-wrapper report-icon">
                  <span class="file-badge">MD</span>
                </div>
                <div class="file-details">
                  <span class="file-name">📝 点击查看：深度调研报告.md</span>
                </div>
              </div>
            </div>
          </div>
          
          <!-- 工具调用中 -->
          <div v-if="research.toolRunning" class="tool-run-state">
            <span class="spinner">⚙️</span>
            <span>正在执行背景检索与事实审查工具...</span>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="chat-input-area">
          <!-- 消息发送前居中占位，作为输入框的上半部分或上方引导 -->
          <div v-if="research.messages.length === 0" class="empty-state-intro">
            <div class="empty-icon-glow">🔬</div>
            <h3>我是您的智能深度研究助手</h3>
            <p>支持多源文件上传、跨领域检索及流式报告生成。生成的报告将提供查看卡片。</p>
          </div>

          <div class="input-container-box">
            <!-- 上传文件预览 (包含文件类型、移除按钮以及 hover 悬浮展示文件全名) -->
            <div v-if="attachedFiles.length > 0" class="input-files-preview">
              <div 
                v-for="(file, idx) in attachedFiles" 
                :key="idx" 
                class="preview-file-chip"
                @mouseenter="file.showFull = true"
                @mouseleave="file.showFull = false"
                :title="file.name"
              >
                <span class="preview-file-icon">📄</span>
                <span class="preview-file-name">{{ truncateName(file.name) }}</span>
                <span class="file-type-badge">{{ file.type.toUpperCase() }}</span>
                <button class="remove-preview-btn" @click="removeAttachedFile(idx)">✖</button>
                <div v-if="file.showFull" class="file-fullname-tooltip">{{ file.name }}</div>
              </div>
            </div>

            <textarea
              ref="textareaEl"
              v-model="input"
              placeholder="上传相关文献，或输入研究课题..."
              :disabled="research.streaming"
              @keydown="handleKeyDown"
            ></textarea>
            
            <div class="input-actions">
              <button class="upload-btn" @click="triggerFileUpload" :disabled="uploading">
                <svg class="btn-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
                </svg>
                {{ uploading ? '上传中...' : '上传文件' }}
              </button>
              <input type="file" ref="fileInput" style="display: none;" @change="handleFileChange" />
              
              <button 
                class="send-btn" 
                :disabled="research.streaming || (!input.trim() && attachedFiles.length === 0)" 
                @click="send"
              >
                {{ research.streaming ? '检索中' : '发送' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 报告/文件查看画布 -->
    <div v-show="showReport" class="report-col card-wrapper">
      <div class="report-tabs">
        <div class="tabs-list">
          <div 
            v-for="tab in tabs" 
            :key="tab.id" 
            class="tab-item"
            :class="{ active: tab.id === activeTabId }"
            @click="activeTabId = tab.id"
          >
            <span>{{ tab.title }}</span>
            <button class="tab-close-btn" @click="closeTab(tab.id, $event)">✖</button>
          </div>
        </div>
        <div class="tab-actions">
          <div class="search-bar-inline" v-if="searchActive">
            <input 
              v-model="searchQuery" 
              placeholder="搜索当前内容..." 
              @keydown.enter="handleSearchEnter"
              ref="searchInput"
            />
            <span class="match-count" v-if="searchQuery">
              {{ searchMatchCount > 0 ? currentHighlightIndex + 1 : 0 }}/{{ searchMatchCount }}
            </span>
            <button class="icon-btn" @click="toggleSearch">✖</button>
          </div>
          <button class="search-toggle-btn" v-else @click="toggleSearch" title="搜索内容">
            🔍 检索
          </button>
        </div>
      </div>
      
      <div 
        class="report-body markdown-body" 
        :class="{ 'confirmed-search': isSearchConfirmed }"
        ref="reportEl" 
        v-html="renderMarkdown(activeTabContent)"
      >
      </div>
    </div>

    <!-- 最右侧浮动刻度栏 -->
    <div v-if="scaleTicks.length > 0" class="tick-nav">
      <div 
        v-for="(tick, idx) in scaleTicks" 
        :key="idx" 
        class="tick-item"
        @click="jumpToTurn(tick.index)"
      >
        <div class="tick-mark"></div>
        <div class="tick-tooltip">{{ tick.userMsg.substring(0, 16) }}...</div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* 简约明亮的主题配置，类似于 ChatGPT 网页版的简约设计 */
.research-layout {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  box-sizing: border-box;

  /* CSS Theme Tokens */
  --research-bg: #f9fafb;
  --research-sidebar-bg: #f3f4f6;
  --research-card-bg: #ffffff;
  --research-border: #e5e7eb;
  --research-text: #0f172a;
  --research-text-muted: #64748b;
  --research-bubble-user: #f4f4f6;
  --research-bubble-user-text: #0f172a;
  --research-bubble-ai: transparent;
  --research-input-bg: #ffffff;
  --research-input-border: #e5e7eb;
  --research-accent: #10b981; /* ChatGPT 经典的亮绿 */
  
  background-color: var(--research-bg);
}



/* 统一卡片基础过渡样式 */
.card-wrapper {
  position: absolute;
  top: 2px;
  height: calc(100vh - 4px);
  box-sizing: border-box;
  transition: all 0.4s cubic-bezier(0.25, 1, 0.5, 1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background-color: var(--research-card-bg);
  border: 1px solid var(--research-border);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  color: var(--research-text);
}

.card-wrapper:hover {
  border-color: rgba(16, 185, 129, 0.15);
}

/* 初始状态：消息历史 1/5， 聊天卡片 4/5 (满屏占满) */
.sidebar-col {
  width: calc(20% - 3px);
  left: 2px;
  background-color: var(--research-sidebar-bg) !important;
}

.chat-col {
  width: calc(80% - 4px);
  left: calc(20% + 1px);
}

.report-col {
  width: calc(100% / 2 - 3px);
  left: calc(100% / 2 + 1px);
  transform: translateX(100%);
  opacity: 0;
  pointer-events: none;
  z-index: 10;
}

/* 展示状态：消息历史缩至 1/6， 聊天卡片缩至 1/3， 报告/文件画布展开为 1/2 */
.has-report .sidebar-col {
  width: calc(100% / 6 - 3px);
  left: 2px;
}

.has-report .chat-col {
  width: calc(100% / 3 - 3px);
  left: calc(100% / 6 + 1px);
}

.has-report .report-col {
  transform: translateX(0);
  opacity: 1;
  pointer-events: auto;
}

/* 顶头部分 */
.chat-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--research-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--research-card-bg);
}

.header-title-area {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.15);
}

.status-pulse.pulsing {
  background: var(--research-accent);
  box-shadow: 0 0 6px var(--research-accent);
  animation: pulse-green 1.6s infinite;
}

@keyframes pulse-green {
  0% { transform: scale(0.9); opacity: 0.5; }
  50% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.5; }
}

.chat-header h2 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--research-text);
}

.back-btn {
  background: transparent;
  border: 1px solid var(--research-border);
  color: var(--research-text-muted);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.back-btn:hover {
  background: var(--research-bubble-user);
  color: var(--research-text);
  border-color: var(--research-input-border);
}

/* 对话主栏容器 */
.chat-content-flex {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.chat-col.is-empty .chat-content-flex {
  justify-content: center;
  padding: 36px;
  gap: 24px;
}

/* 消息内容流 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.msg-wrapper {
  max-width: 85%;
}
.msg-wrapper.user {
  align-self: flex-end;
}
.msg-wrapper.assistant {
  align-self: flex-start;
}

.msg-bubble {
  font-size: 14px;
  line-height: 1.6;
}

.msg-wrapper.user .msg-bubble {
  background-color: var(--research-bubble-user);
  color: var(--research-bubble-user-text);
  border-radius: 18px;
  padding: 10px 16px;
  border: none;
}

.msg-wrapper.assistant .msg-bubble {
  background-color: transparent;
  color: var(--research-text);
  padding: 10px 0;
  border: none;
  border-radius: 0;
}

/* 文件附件卡片 */
.message-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.file-attachment-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--research-card-bg);
  border: 1px solid var(--research-border);
  border-radius: 6px;
  cursor: pointer;
  max-width: 240px;
  transition: all 0.2s ease;
}

.file-attachment-card:hover {
  background: var(--research-bubble-user);
  border-color: var(--research-input-border);
  transform: translateY(-1px);
}

.report-card-btn {
  background: rgba(16, 185, 129, 0.05);
  border-color: rgba(16, 185, 129, 0.2);
}
.report-card-btn:hover {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.3);
}

.file-icon-wrapper {
  background: var(--research-bubble-user);
  min-width: 28px;
  height: 22px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.report-icon {
  background: rgba(16, 185, 129, 0.15);
}

.file-badge {
  font-size: 8px;
  font-weight: 700;
  color: var(--research-text-muted);
}
.report-icon .file-badge {
  color: var(--research-accent);
}

.file-name {
  font-size: 12px;
  color: var(--research-text);
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
}

/* 初始空状态 */
.empty-state-intro {
  text-align: center;
  color: var(--research-text-muted);
  max-width: 80%;
  margin: 0 auto 24px auto;
}

.empty-icon-glow {
  font-size: 36px;
  margin-bottom: 12px;
}

.empty-state-intro h3 {
  color: var(--research-text);
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}

.empty-state-intro p {
  font-size: 12.5px;
  line-height: 1.5;
}

/* 正在思考/工具执行 */
.tool-run-state {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--research-text-muted);
  align-self: flex-start;
  background: var(--research-bubble-user);
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--research-border);
}
.tool-run-state .spinner {
  display: inline-block;
  animation: spin 3s infinite linear;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 输入表单框 */
.chat-input-area {
  background: var(--research-card-bg);
  border-top: 1px solid var(--research-border);
  padding: 14px;
  display: flex;
  flex-direction: column;
}

.chat-content-flex.is-centered {
  justify-content: center;
  align-items: center;
  padding: 24px;
  height: 100%;
}

.chat-content-flex.is-centered .chat-input-area {
  border-top: none;
  background: transparent;
  padding: 0;
  width: 100%;
  max-width: 480px;
}

.input-container-box {
  width: 100%;
  box-sizing: border-box;
}

.chat-content-flex.is-centered .input-container-box {
  border: 1px solid var(--research-input-border);
  border-radius: var(--radius-md);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);
  padding: 14px;
  background: var(--research-card-bg);
}

/* 上传预览小片 */
.preview-file-chip {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--research-bubble-user);
  border: 1px solid var(--research-border);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
}

.file-type-badge {
  font-size: 8px;
  font-weight: 700;
  color: var(--research-text-muted);
  background: rgba(0, 0, 0, 0.05);
  padding: 1px 4px;
  border-radius: 3px;
}

.file-fullname-tooltip {
  position: absolute;
  bottom: 125%;
  left: 50%;
  transform: translateX(-50%);
  background: #1f1f21;
  color: #ffffff;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  z-index: 999;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: none;
}

.file-fullname-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #1f1f21;
}

.chat-input-area textarea {
  width: 100%;
  min-height: 44px;
  max-height: 180px;
  background: transparent;
  border: none;
  padding: 8px 0;
  color: var(--research-text);
  font-family: inherit;
  resize: none;
  font-size: 13.5px;
  line-height: 1.5;
  box-sizing: border-box;
}
.chat-input-area textarea:focus {
  outline: none;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
}

.upload-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--research-input-border);
  color: var(--research-text-muted);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.upload-btn:hover {
  background: var(--research-bubble-user);
  color: var(--research-text);
}

.send-btn {
  background: var(--research-accent);
  border: 1px solid var(--research-accent);
  color: #fff;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.send-btn:hover {
  filter: brightness(1.08);
}
.send-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* 输入框文件预览 */
.input-files-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--research-border);
}

.preview-file-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--research-bubble-user);
  border: 1px solid var(--research-border);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  color: var(--research-text);
}

.remove-preview-btn {
  background: transparent;
  border: none;
  color: var(--research-text-muted);
  cursor: pointer;
  font-size: 10px;
  margin-left: 2px;
}
.remove-preview-btn:hover {
  color: #ef4444;
}

/* 1/2 Canvas 标签导航 */
.report-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--research-bubble-user);
  border-bottom: 1px solid var(--research-border);
  padding: 0 10px;
  height: 40px;
}

.tabs-list {
  display: flex;
  gap: 2px;
  overflow-x: auto;
  height: 100%;
  align-items: flex-end;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--research-text-muted);
  cursor: pointer;
  border-top-left-radius: 4px;
  border-top-right-radius: 4px;
  border: 1px solid transparent;
  border-bottom: none;
  background: transparent;
  height: calc(100% - 2px);
  transition: all 0.2s;
}

.tab-item:hover {
  color: var(--research-text);
  background: rgba(0, 0, 0, 0.02);
}

.tab-item.active {
  color: var(--research-accent);
  background: var(--research-card-bg);
  border-color: var(--research-border);
  font-weight: 500;
  box-shadow: inset 0 2px 0 var(--research-accent);
}

.tab-close-btn {
  background: transparent;
  border: none;
  color: var(--research-text-muted);
  cursor: pointer;
  font-size: 9px;
  padding: 2px;
}
.tab-close-btn:hover {
  color: #ef4444;
}

/* Canvas 搜索 */
.tab-actions {
  display: flex;
  align-items: center;
}

.search-bar-inline {
  display: flex;
  align-items: center;
  background: var(--research-card-bg);
  border: 1px solid var(--research-input-border);
  border-radius: 6px;
  padding: 2px 6px;
  gap: 6px;
}
.search-bar-inline input {
  background: transparent;
  border: none;
  color: var(--research-text);
  outline: none;
  font-size: 11.5px;
  width: 140px;
}
.match-count {
  font-size: 10.5px;
  color: var(--research-text-muted);
}

.icon-btn, .search-toggle-btn {
  background: transparent;
  border: none;
  color: var(--research-text-muted);
  cursor: pointer;
  font-size: 11.5px;
}
.search-toggle-btn {
  padding: 6px 10px;
  border-radius: 4px;
}
.search-toggle-btn:hover {
  background: rgba(0,0,0,0.03);
  color: var(--research-text);
}
.icon-btn:hover {
  color: var(--research-text);
}

/* Canvas 报告主体 */
.report-body {
  flex: 1;
  overflow-y: auto;
  padding: 28px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--research-text);
  background-color: var(--research-card-bg);
}

/* 双色高亮 */
:deep(mark.search-highlight) {
  background-color: rgba(59, 130, 246, 0.25); /* 检索打字阶段 - 蓝色 */
  color: #1d4ed8;
  border-radius: 2px;
  padding: 1px 2px;
}


.confirmed-search :deep(mark.search-highlight) {
  background-color: rgba(245, 158, 11, 0.3) !important; /* 按下回车后 - 橙色 */
  color: #b45309 !important;
}


.confirmed-search :deep(mark.search-highlight.current) {
  background-color: rgba(245, 158, 11, 0.75) !important;
  color: #fff !important;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, 1);
}

/* 刻度侧边条 */
.tick-nav {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 100;
}
.tick-mark {
  width: 4px;
  height: 14px;
  background: rgba(0, 0, 0, 0.12);
  border-radius: 2px;
  transition: all 0.2s;
}

.tick-tooltip {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  background: var(--research-card-bg);
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s;
  color: var(--research-accent);
  font-weight: 500;
  border: 1px solid var(--research-border);
  box-shadow: 0 2px 10px rgba(0,0,0,0.05);
}
.tick-item:hover .tick-mark {
  background: var(--research-accent);
  transform: scaleY(1.25);
}
.tick-item:hover .tick-tooltip {
  opacity: 1;
}

/* 📝 Scoped Markdown body styling for Deep Research text legibility */
:deep(.markdown-body) {
  color: var(--research-text);
  font-family: inherit;
  font-size: 14.5px;
  line-height: 1.7;
}

:deep(.markdown-body p) {
  color: var(--research-text);
  margin-bottom: 12px;
  line-height: 1.7;
}

:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}

:deep(.markdown-body strong) {
  color: var(--research-text);
  font-weight: 700;
}

:deep(.markdown-body ul), :deep(.markdown-body ol) {
  margin: 8px 0 14px 20px;
}

:deep(.markdown-body li) {
  color: var(--research-text);
  margin-bottom: 6px;
  line-height: 1.65;
}

:deep(.markdown-body a) {
  color: var(--research-accent);
  text-decoration: none;
}

:deep(.markdown-body a:hover) {
  text-decoration: underline;
}

:deep(.markdown-body h1), :deep(.markdown-body h2), :deep(.markdown-body h3), :deep(.markdown-body h4) {
  color: var(--research-text);
  margin-top: 16px;
  margin-bottom: 8px;
  font-weight: 600;
}
</style>

<style>
/* 深度研究看板 - 暗黑模式变量全局覆盖 */
html.dark .research-layout {
  --research-bg: #171717 !important;
  --research-sidebar-bg: #171717 !important;
  --research-card-bg: #212121 !important;
  --research-border: rgba(255, 255, 255, 0.08) !important;
  --research-text: #ececec !important;
  --research-text-muted: #9ca3af !important;
  --research-bubble-user: #2f2f2f !important;
  --research-bubble-user-text: #ececec !important;
  --research-bubble-ai: transparent !important;
  --research-input-bg: #212121 !important;
  --research-input-border: rgba(255, 255, 255, 0.1) !important;
  --research-accent: #10b981 !important;
  
  background-color: var(--research-bg) !important;
}

html.dark .status-pulse {
  background: rgba(255, 255, 255, 0.15) !important;
}

html.dark .tick-mark {
  background: rgba(255, 255, 255, 0.15) !important;
}

/* 检索词高亮暗色主题 */
html.dark mark.search-highlight {
  color: #93c5fd !important;
  background-color: rgba(59, 130, 246, 0.4) !important;
}

html.dark .confirmed-search mark.search-highlight {
  color: #fcd34d !important;
  background-color: rgba(245, 158, 11, 0.5) !important;
}
</style>
