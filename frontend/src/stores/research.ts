import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiUrl, getAuthHeaders } from '@/services/api'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  files?: { id: string; name: string; type: string }[]
}

export const useResearchStore = defineStore('research', () => {
  const currentId = ref<string | null>(null)
  const messages = ref<ChatMessage[]>([])
  const reportContent = ref<string>('')
  const streaming = ref(false)
  const toolRunning = ref(false)
  const sessions = ref<any[]>([])

  async function fetchSessions() {
    try {
      const res = await fetch(apiUrl('/research/sessions'), {
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
      const res = await fetch(apiUrl(`/research/sessions/${id}`), {
        headers: getAuthHeaders(),
      })
      if (res.status === 401) {
        window.location.href = '/login'
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      currentId.value = data.id
      messages.value = data.messages
      if (data.report) {
        reportContent.value = data.report.report_md || ''
      } else {
        reportContent.value = ''
      }
    } catch (e) {
      console.error('[fetchSessionDetails] error:', e)
    }
  }

  function newSession() {
    currentId.value = null
    messages.value = []
    reportContent.value = ''
  }

  async function send(text: string, attachedFiles?: { id: string; name: string; type: string }[]) {
    if (!text.trim() || streaming.value) return

    const fileIds = attachedFiles ? attachedFiles.map(f => f.id) : null;
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
      const res = await fetch(apiUrl('/reports/stream'), {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          query: text,
          file_ids: fileIds,
          session_id: currentId.value || null
        }),
      })

      if (res.status === 401) {
        // Token 过期，直接踢回登录页，实际可以调用 logout
        window.location.href = '/login'
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      await readDualStream(res, msgIndex)
      // 发送成功后刷新会话列表，获取可能新生成的会话 ID/标题
      await fetchSessions()
    } catch (e: any) {
      console.error('[send research] 异常:', e)
      const msg = messages.value[msgIndex]
      if (msg) msg.content = `错误: ${e.message}`
    } finally {
      streaming.value = false
      toolRunning.value = false
    }
  }

  async function readDualStream(res: Response, msgIndex: number) {
    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    
    // 用于打字机效果的变量
    let pendingChat = ''
    let animatingChat = false
    
    let pendingReport = ''
    let animatingReport = false

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

    function tickReport() {
      if (!pendingReport) {
        animatingReport = false
        return
      }
      reportContent.value += pendingReport[0]
      pendingReport = pendingReport.slice(1)
      requestAnimationFrame(tickReport)
    }

    function pushChat(text: string) {
      pendingChat += text
      if (!animatingChat) {
        animatingChat = true
        tickChat()
      }
    }

    function pushReport(text: string) {
      pendingReport += text
      if (!animatingReport) {
        animatingReport = true
        tickReport()
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
              case 'session_id':
                currentId.value = event.session_id
                break
              case 'chat':
                if (event.content) {
                  const msg = messages.value[msgIndex]
                  if (msg && msg.content.startsWith('⚙️')) {
                    msg.content = '' // 清除工具调用的提示文字
                  }
                  toolRunning.value = false
                  pushChat(event.content.replace(/\\n/g, '\n'))
                }
                break
              case 'report':
                if (event.content) {
                  pushReport(event.content.replace(/\\n/g, '\n'))
                }
                break
              case 'tool':
                toolRunning.value = true
                const toolMsg = messages.value[msgIndex]
                if (toolMsg) {
                  toolMsg.content = `⚙️ **[Operator System]** AI 正在执行深度检索工具: \`${event.tool}\` ...\n\n`
                  messages.value = [...messages.value]
                }
                break
              case 'error':
                console.error('[readDualStream] Error:', event.error)
                break
            }
            
            // 针对最后一条 status: done 消息
            if (event.status === 'done') {
              console.log('Stream done, report_id:', event.report_id)
              // 自动切换为当前的 session_id
              if (event.report_id) {
                // 如果当前没有 session_id，我们可以从数据库拿或者流输出中有，其实后端已经在创建时分配了
                // 为简便起见，当 stream done 后 fetchSessions 可以拿到最新的 id
              }
            }
          } catch (err) {
            // 解析失败（可能切片不完整），忽略继续
          }
        }
      }
    } finally {
      toolRunning.value = false
    }

    // 尾部剩余的 buffer 处理
    if (buffer.startsWith('data: ')) {
      try {
        const event = JSON.parse(buffer.slice(6))
        if (event.status === 'done') console.log('Final done.')
      } catch (e) {}
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
