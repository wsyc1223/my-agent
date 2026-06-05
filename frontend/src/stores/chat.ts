import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiUrl, getAuthHeaders } from '@/services/api'

export interface Conversation {
  id: string
  title: string
  created_at: string | null
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const loading = ref(false)
  const userId = ref(localStorage.getItem('userId') || '')
  const userName = ref(localStorage.getItem('userName') || '')
  const interrupted = ref(false)
  const interruptThreadId = ref<string | null>(null)
  const interruptConvId = ref<string | null>(null)
  const approving = ref(false)
  const toolRunning = ref(false) // 当前 Agent 是否在执行后台工具

  // 安全退出登录方法
  function logout() {
    localStorage.removeItem('token')
    localStorage.removeItem('userName')
    localStorage.removeItem('userId')
    userId.value = ''
    userName.value = ''
    conversations.value = []
    messages.value = []
    currentId.value = null
  }

  async function fetchConversations() {
    const token = localStorage.getItem('token')
    if (!token) return
    
    try {
      const res = await fetch(apiUrl('/conversations'), {
        headers: getAuthHeaders()
      })
      if (res.status === 401) {
        logout()
        return
      }
      conversations.value = await res.json()
    } catch (e) {
      console.error('[fetchConversations] 异常:', e)
    }
  }

  async function fetchMessages(id: string) {
    currentId.value = id
    loading.value = true
    try {
      const res = await fetch(apiUrl(`/conversations/${id}/messages`), {
        headers: getAuthHeaders()
      })
      if (res.status === 401) {
        logout()
        loading.value = false
        return
      }
      messages.value = await res.json()
    } catch (e) {
      console.error('[fetchMessages] 异常:', e)
    } finally {
      loading.value = false
    }
  }

  function newConversation() {
    currentId.value = null
    messages.value = []
  }

  async function readStream(res: Response, msgIndex: number) {
    console.log(`[readStream] 开始读取统一标准化 JSON 数据流，目标消息索引: ${msgIndex}`);
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    let pending = ''
    let animating = false
    let hasTextStarted = false // 标记大模型是否已经真正开始吐字正文

    function flush() {
      if (animating || !pending) return
      animating = true
      const tick = () => {
        if (!pending) { 
          animating = false; 
          return 
        }
        const msg = messages.value[msgIndex]
        if (msg) {
          msg.content += pending[0]
          // 强制触发 Vue 3 响应式数组更新
          messages.value = [...messages.value]
        }
        pending = pending.slice(1)
        requestAnimationFrame(tick)
      }
      tick()
    }

    function push(text: string) {
      pending += text
      flush()
    }

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

            console.log('[readStream] 捕获标准化事件:', event.type);

            switch (event.type) {
              case 'conversation_id':
                currentId.value = event.conversation_id
                break
              case 'tool_run':
                toolRunning.value = true
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
                    toolRunning.value = false
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
                toolRunning.value = false
                interruptThreadId.value = event.thread_id
                interruptConvId.value = event.conversation_id
                return
              case 'done':
                console.log('[readStream] 收到统一流结束信号 done');
                toolRunning.value = false
                break
              case 'error':
                console.error('[readStream] 收到后端异常信令:', event.message);
                toolRunning.value = false
                const errMsg = messages.value[msgIndex]
                if (errMsg) errMsg.content = `错误: ${event.message}`
                break
              default:
                console.warn('[readStream] 收到未定义类型的事件信令:', event.type)
            }
          } catch (err) {
            console.error('[readStream] JSON 信令解析失败，payload:', payload, '错误:', err)
          }
        }
      }
    } finally {
      toolRunning.value = false
    }

    if (buffer.startsWith('data: ')) {
      const payload = buffer.slice(6)
      try {
        const event = JSON.parse(payload)
        if (event && typeof event === 'object' && event.type === 'conversation_id') {
          currentId.value = event.conversation_id
        }
      } catch (err) {
        console.error('[readStream] 尾部缓冲区解析失败:', err)
      }
    }
  }

  async function send(text: string) {
    if (!text.trim() || streaming.value) return

    messages.value.push({ role: 'user', content: text })
    streaming.value = true
    interrupted.value = false
    toolRunning.value = false

    messages.value.push({ role: 'assistant', content: '' })
    const msgIndex = messages.value.length - 1

    try {
      const res = await fetch(apiUrl('/agent/chat/stream'), {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          message: text,
          conversation_id: currentId.value || null
        }),
      })

      if (res.status === 401) {
        logout()
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      await readStream(res, msgIndex)
      await fetchConversations()
    } catch (e: any) {
      console.error('[send] 异常:', e);
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
      toolRunning.value = false
    } finally {
      streaming.value = false
      toolRunning.value = false
    }
  }

  async function approveTool() {
    if (!interruptThreadId.value) return
    console.log(`[approveTool] 批准工具运行，thread_id: ${interruptThreadId.value}`);
    approving.value = true
    interrupted.value = false
    toolRunning.value = true

    const last = messages.value[messages.value.length - 1]
    if (last && last.content) {
      messages.value.push({ role: 'assistant', content: '' })
    }
    const msgIndex = messages.value.length - 1

    try {
      const res = await fetch(apiUrl('/agent/resume'), {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          thread_id: interruptThreadId.value,
          conversation_id: interruptConvId.value,
          approved: true,
        }),
      })

      if (res.status === 401) {
        logout()
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      streaming.value = true
      await readStream(res, msgIndex)
      await fetchConversations()
    } catch (e: any) {
      console.error('[approveTool] 异常:', e);
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
      toolRunning.value = false
    } finally {
      streaming.value = false
      approving.value = false
      toolRunning.value = false
    }
  }

  async function rejectTool() {
    if (!interruptThreadId.value) return
    console.log(`[rejectTool] 拒绝工具运行，thread_id: ${interruptThreadId.value}`);
    approving.value = true
    interrupted.value = false
    toolRunning.value = false

    messages.value.push({ role: 'assistant', content: '' })
    const msgIndex = messages.value.length - 1

    try {
      const res = await fetch(apiUrl('/agent/resume'), {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          thread_id: interruptThreadId.value,
          conversation_id: interruptConvId.value,
          approved: false,
        }),
      })

      if (res.status === 401) {
        logout()
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      streaming.value = true
      await readStream(res, msgIndex)
      await fetchConversations()
    } catch (e: any) {
      console.error('[rejectTool] 异常:', e);
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
    } finally {
      streaming.value = false
      approving.value = false
      toolRunning.value = false
    }
  }

  return {
    conversations, currentId, messages, streaming, loading, userId, userName,
    interrupted, interruptThreadId, interruptConvId, approving, toolRunning,
    fetchConversations, fetchMessages, newConversation, send, logout,
    approveTool, rejectTool,
  }
})
