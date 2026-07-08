import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiUrl, getAuthHeaders } from '@/services/api'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'subagent'
  content: string
  files?: { id: string; name: string; type: string }[]
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

export const useResearchStore = defineStore('research', () => {
  const currentId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const reportContent = ref<string>('')
  const streaming = ref(false)
  const toolRunning = ref(false)
  const sessions = ref<any[]>([])
  
  // 保存遥测监听的 Reader，以便在切换会话时能安全关闭它
  let telemetryReader: ReadableStreamDefaultReader<Uint8Array> | null = null

  async function fetchSessions() {
    try {
      const res = await fetch(apiUrl('/conversations'), {
        headers: getAuthHeaders(),
      })
      if (res.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      sessions.value = await res.json()
    } catch (e) {
      console.error('[fetchSessions] error:', e)
    }
  }

  async function fetchSessionDetails(id: string) {
    try {
      // 停止上一场会话的遥测监听
      if (telemetryReader) {
        await telemetryReader.cancel()
        telemetryReader = null
      }

      const res = await fetch(apiUrl(`/conversations/${id}/messages`), {
        headers: getAuthHeaders(),
      })
      if (res.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const messagesData = await res.json()
      
      currentId.value = id
      messages.value = messagesData

      // 尝试获取当前会话下的最后一份报告内容
      reportContent.value = ''
      const subagentMsgs = messagesData.filter((m: any) => m.role === 'subagent' && m.task?.report_id)
      if (subagentMsgs.length > 0) {
        const lastTaskMsg = subagentMsgs[subagentMsgs.length - 1]
        if (lastTaskMsg.task?.report_id) {
          await fetchReportDetail(lastTaskMsg.task.report_id)
        }
      }

      // 开启遥测通道监听
      listenTelemetry(id)
    } catch (e) {
      console.error('[fetchSessionDetails] error:', e)
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
      console.error('[fetchReportDetail] 错误:', e)
    }
  }

  function newSession() {
    if (telemetryReader) {
      telemetryReader.cancel()
      telemetryReader = null
    }
    currentId.value = null
    messages.value = []
    reportContent.value = ''
  }

  async function send(text: string, attachedFiles?: { id: string; name: string; type: string }[]) {
    if (!text.trim() || streaming.value) return

    messages.value.push({
      role: 'user',
      content: text,
      files: attachedFiles || []
    })
    streaming.value = true
    toolRunning.value = false

    messages.value.push({ role: 'assistant', content: '' })
    const msgIndex = messages.value.length - 1

    try {
      const res = await fetch(apiUrl('/agent/chat/stream'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders()
        },
        body: JSON.stringify({
          message: text,
          conversation_id: currentId.value || null,
          global_memory: false
        }),
      })

      if (res.status === 401) {
        window.location.href = '/login'
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      await readStream(res, msgIndex)
      await fetchSessions()
      
      if (currentId.value) {
        listenTelemetry(currentId.value)
      }
    } catch (e: any) {
      console.error('[send research] 异常:', e)
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
    } finally {
      streaming.value = false
      toolRunning.value = false
    }
  }

  async function readStream(res: Response, msgIndex: number) {
    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    
    let pendingChat = ''
    let animatingChat = false
    let hasTextStarted = false

    function tickChat() {
      if (!pendingChat) {
        animatingChat = false
        return
      }
      const msg = messages.value[msgIndex]
      if (msg) {
        msg.content += pendingChat[0]
        messages.value = [...messages.value]
      }
      pendingChat = pendingChat.slice(1)
      requestAnimationFrame(tickChat)
    }

    function pushChat(text: string) {
      pendingChat += text
      if (!animatingChat) {
        animatingChat = true
        tickChat()
      }
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
                  pushChat(event.content.replace(/\\n/g, '\n'))
                }
                break
              case 'tool_run':
                toolRunning.value = true
                const toolMsg = messages.value[msgIndex]
                if (toolMsg) {
                  const displayNames = event.tool_names ? event.tool_names.join(', ') : 'tool'
                  toolMsg.content = `⚙️ **[Operator System]** AI 正在执行深度检索工具: \`${displayNames}\` ...\n\n`
                  messages.value = [...messages.value]
                }
                break
              case 'error':
                console.error('[readStream] Error:', event.message)
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

            console.log('[Telemetry Event]', event)

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
          } catch (e) {
            // ignore
          }
        }
      }
    } catch (e: any) {
      console.log('[listenTelemetry] 长连接断开或被用户手动取消:', e.message)
    }
  }

  return {
    currentId,
    messages,
    reportContent,
    streaming,
    toolRunning,
    sessions,
    send,
    fetchSessions,
    fetchSessionDetails,
    newSession
  }
})
