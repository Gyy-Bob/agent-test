/** 后端 API 调用封装 */

export interface ChatDelta {
  type: 'meta' | 'delta' | 'done' | 'error'
  conversation_id?: string
  content?: string
  message?: string
}

/** SSE 流式对话：每收到一段增量文本调用 onDelta */
export async function chatStream(
  content: string,
  conversationId: string | null,
  onDelta: (text: string) => void,
  onMeta: (conversationId: string) => void,
): Promise<void> {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, conversation_id: conversationId }),
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || `请求失败 (${resp.status})`)
  }

  const reader = resp.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      const event: ChatDelta = JSON.parse(line.slice(5))
      if (event.type === 'meta' && event.conversation_id) onMeta(event.conversation_id)
      if (event.type === 'delta' && event.content) onDelta(event.content)
      if (event.type === 'error') throw new Error(event.message || '模型返回错误')
    }
  }
}

export interface ExcelResult {
  status: 'done' | 'need_clarification'
  task_id: string
  download_url?: string
  output_file?: string
  result_rows?: number
  summary?: string
  ambiguities?: string[]
  plan_desc?: string
}

/** 上传 Excel 并汇总 */
export async function summarizeExcel(
  files: File[],
  query: string,
): Promise<ExcelResult> {
  const form = new FormData()
  form.append('query', query)
  files.forEach((f) => form.append('files', f))
  const resp = await fetch('/api/excel/summarize', {
    method: 'POST',
    body: form,
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.detail || `请求失败 (${resp.status})`)
  return data
}
