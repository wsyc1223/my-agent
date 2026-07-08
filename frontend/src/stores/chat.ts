import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiUrl, getAuthHeaders } from '@/services/api'

export interface Conversation {
  id: string
  title: string
  created_at: string | null
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'subagent'
  content: string
  referred_message_id?: string | null
  associated_task_id?: string | null
  task?: {
    id: string
    task_type: string
    status: string
    referred_message_id?: number | null
    report_id?: string | null
    error_message?: string | null
  } | null
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
  const toolRunning = ref(false)
  const sidebarCollapsed = ref(false)
  const globalMemory = ref(localStorage.getItem('globalMemory') === 'true')
  
  // 深度研究的报告正文
  const reportContent = ref('')
  
  // 遥测接口监听的 Reader 句柄，防范多开连接
  let telemetryReader: ReadableStreamDefaultReader<Uint8Array> | null = null

  function setGlobalMemory(val: boolean) {
    globalMemory.value = val
    localStorage.setItem('globalMemory', String(val))
  }

  function logout() {
    if (telemetryReader) {
      telemetryReader.cancel()
      telemetryReader = null
    }
    localStorage.removeItem('token')
    localStorage.removeItem('userName')
    localStorage.removeItem('userId')
    userId.value = ''
    userName.value = ''
    conversations.value = []
    messages.value = []
    currentId.value = null
    reportContent.value = ''
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
    
    // 关闭上一场的遥测
    if (telemetryReader) {
      await telemetryReader.cancel()
      telemetryReader = null
    }

    try {
      const res = await fetch(apiUrl(`/conversations/${id}/messages`), {
        headers: getAuthHeaders()
      })
      if (res.status === 401) {
        logout()
        loading.value = false
        return
      }
      const data = await res.json()
      messages.value = data

      // 自动提取历史里最后生成的报告进行右侧加载呈现
      reportContent.value = ''
      const subagentMsgs = data.filter((m: any) => m.role === 'subagent' && m.task?.report_id)
      if (subagentMsgs.length > 0) {
        const lastMsg = subagentMsgs[subagentMsgs.length - 1]
        if (lastMsg.task?.report_id) {
          await fetchReportDetail(lastMsg.task.report_id)
        }
      }

      // 开启新会话的遥测长连接
      listenTelemetry(id)
    } catch (e) {
      console.error('[fetchMessages] 异常:', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchReportDetail(reportId: string) {
    try {
      const res = await fetch(apiUrl(`/reports/${reportId}`), {
        headers: getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        if (data && data.report_md) {
          reportContent.value = data.report_md
        }
      }
    } catch (e) {
      console.error('[fetchReportDetail] 获取报告失败:', e)
    }
  }

  function newConversation() {
    if (telemetryReader) {
      telemetryReader.cancel()
      telemetryReader = null
    }
    currentId.value = null
    messages.value = []
    reportContent.value = ''
  }

  async function readStream(res: Response, msgIndex: number) {
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    let pending = ''
    let animating = false
    let hasTextStarted = false

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
                interrupted.value = true
                toolRunning.value = false
                interruptThreadId.value = event.thread_id
                interruptConvId.value = event.conversation_id
                return
              case 'done':
                toolRunning.value = false
                break
              case 'error':
                toolRunning.value = false
                const errMsg = messages.value[msgIndex]
                if (errMsg) errMsg.content = `错误: ${event.message}`
                break
            }
          } catch (err) {
            // ignore
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
      } catch (err) {}
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
          conversation_id: currentId.value || null,
          global_memory: globalMemory.value
        }),
      })

      if (res.status === 401) {
        logout()
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      await readStream(res, msgIndex)
      await fetchConversations()

      if (currentId.value) {
        listenTelemetry(currentId.value)
      }
    } catch (e: any) {
      console.error('[send] 异常:', e)
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
      toolRunning.value = false
    } finally {
      streaming.value = false
      toolRunning.value = false
    }
  }

  async function listenTelemetry(conversationId: string) {
    if (telemetryReader) {
      await telemetryReader.cancel()
      telemetryReader = null
    }

    try {
      const res = await fetch(apiUrl(`/conversations/${conversationId}/telemetry`), {
        headers: getAuthHeaders()
      })
      if (!res.ok) throw new Error(`Telemetry HTTP ${res.status}`)
      if (!res.body) return

      telemetryReader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await telemetryReader.read()
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

            console.log('[Chat Telemetry Event]', event)

            if (event.type === 'subagent_result') {
              const taskData = event.task
              const taskMsg = event.message

              const existIdx = messages.value.findIndex(m => m.associated_task_id === taskData.id)
              if (existIdx !== -1) {
                messages.value[existIdx] = {
                  role: 'subagent',
                  content: taskMsg.content,
                  referred_message_id: taskMsg.referred_message_id,
                  associated_task_id: taskData.id,
                  task: taskData
                }
              } else {
                messages.value.push({
                  role: 'subagent',
                  content: taskMsg.content,
                  referred_message_id: taskMsg.referred_message_id,
                  associated_task_id: taskData.id,
                  task: taskData
                })
              }
              messages.value = [...messages.value]

              if (taskData.status === 'success' && taskData.report_id) {
                await fetchReportDetail(taskData.report_id)
              }
            }
          } catch (e) {}
        }
      }
    } catch (e: any) {
      console.log('[listenTelemetry] 断开或取消:', e.message)
    }
  }

  async function approveTool() {
    if (!interruptThreadId.value) return
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
      console.error('[approveTool] 异常:', e)
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
      console.error('[rejectTool] 异常:', e)
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
    sidebarCollapsed, globalMemory, reportContent,
    fetchConversations, fetchMessages, newConversation, send, logout,
    approveTool, rejectTool, setGlobalMemory, fetchReportDetail
  }
})
