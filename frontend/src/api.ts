/** 后端 API + 云端 LLM 调用封装 */

import { cloud } from './cloud'
import { EXCEL_PLAN_SYSTEM_PROMPT, EXCEL_SUMMARY_SYSTEM_PROMPT } from './skillPrompts'

/* ============ 云端模型 ============ */

export interface CloudModel {
  id: string
  name?: string
  disabled?: boolean
}

/** 拉取可用模型列表（空列表是合法结果） */
export async function listModels(): Promise<CloudModel[]> {
  const models = await cloud.llm.models.list()
  return (models as CloudModel[]) ?? []
}

/** 通用一次性云 LLM 调用（stream:true 收集完整文本） */
export async function llmComplete(
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: string }>,
  modelId: string,
  opts?: { jsonMode?: boolean; conversationId?: string },
): Promise<string> {
  let answer = ''
  const params: Record<string, unknown> = {
    model: modelId,
    messages,
    stream: true,
  }
  if (opts?.jsonMode) params.response_format = { type: 'json_object' }
  if (opts?.conversationId) params.conversationId = opts.conversationId

  for await (const chunk of cloud.llm.chat.completions.create(params as never)) {
    const delta = (chunk as { choices?: Array<{ delta?: { content?: string } }> }).choices?.[0]
    if (delta?.delta?.content) answer += delta.delta.content
  }
  return answer
}

/* ============ F1 对话：云 LLM 流式 + 后端历史持久化 ============ */

export async function chatStream(
  content: string,
  history: Array<{ role: 'user' | 'assistant'; content: string }>,
  modelId: string,
  onDelta: (text: string) => void,
): Promise<string> {
  let full = ''
  // 注意：不传 conversationId —— 云端 CORS 白名单暂未放行 X-Conversation-ID 头，
  // 多轮上下文由 messages 数组维护，不受影响
  const params: Record<string, unknown> = {
    model: modelId,
    messages: [
      { role: 'system', content: '你是 agent-test 智能助手，用简体中文回答，语言简洁、直接、有帮助。' },
      ...history,
      { role: 'user', content },
    ],
    stream: true,
  }
  for await (const chunk of cloud.llm.chat.completions.create(params as never)) {
    const delta = (chunk as { choices?: Array<{ delta?: { content?: string } }> }).choices?.[0]
    const text = delta?.delta?.content
    if (text) {
      full += text
      onDelta(text)
    }
  }
  return full
}

/** 保存一轮对话到后端 */
export async function saveMessages(
  conversationId: string,
  userContent: string,
  assistantContent: string,
): Promise<void> {
  await fetch('/api/chat/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      user_content: userContent,
      assistant_content: assistantContent,
    }),
  })
}

/* ============ F2 Excel 汇总 ============ */

export interface FileProfile {
  file: string
  sheets: Array<{
    sheet_name: string
    rows: number
    columns: Array<{ name: string; dtype: string }>
    sample_rows: string[][]
  }>
}

/** 上传文件，返回任务 ID 与数据概况 */
export async function uploadExcel(files: File[]): Promise<{ task_id: string; profiles: FileProfile[] }> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  const resp = await fetch('/api/excel/upload', { method: 'POST', body: form })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.detail || `上传失败 (${resp.status})`)
  return data
}

export interface ExcelPlan {
  action: string
  files_involved?: string[]
  join_keys?: string[]
  group_by?: string[]
  aggregations?: Array<{ field: string; func?: string }>
  output_columns?: string[]
  expression?: string
  sort_by?: Array<{ field: string; order?: string }>
  order?: string
  limit?: number
  ambiguities?: string[]
  plan_desc?: string
}

/** 用云 LLM 生成 JSON 处理计划 */
export async function generatePlan(
  profiles: FileProfile[],
  query: string,
  modelId: string,
): Promise<ExcelPlan> {
  const raw = await llmComplete(
    [
      {
        role: 'system',
        content: EXCEL_PLAN_SYSTEM_PROMPT.replace(
          '{profile}',
          JSON.stringify(profiles, null, 2),
        ),
      },
      { role: 'user', content: query },
    ],
    modelId,
    { jsonMode: true },
  )
  // 稳健提取 JSON
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/)
  const text = fence ? fence[1] : raw
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start === -1 || end === -1) throw new Error('模型未返回有效的处理计划')
  return JSON.parse(text.slice(start, end + 1))
}

export interface ExecuteResult {
  task_id: string
  download_url: string
  output_file: string
  result_rows: number
  result_columns: string[]
  sample_rows: string[][]
}

/** 提交计划给后端执行，返回结果与下载链接 */
export async function executePlan(
  taskId: string,
  query: string,
  plan: ExcelPlan,
): Promise<ExecuteResult> {
  const resp = await fetch('/api/excel/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, query, plan }),
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.detail || `执行失败 (${resp.status})`)
  return data
}

/** 用云 LLM 生成结果总结 */
export async function generateSummary(
  result: ExecuteResult,
  query: string,
  modelId: string,
): Promise<string> {
  return llmComplete(
    [
      { role: 'system', content: EXCEL_SUMMARY_SYSTEM_PROMPT },
      {
        role: 'user',
        content: `用户需求：${query}\n结果总行数：${result.result_rows}\n结果列：${result.result_columns.join(
          '、',
        )}\n结果前5行：\n${result.sample_rows
          .map((r) => r.join(' | '))
          .join('\n')}\n\n请总结。`,
      },
    ],
    modelId,
  )
}
