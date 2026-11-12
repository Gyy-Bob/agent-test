import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Input,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import {
  DownloadOutlined,
  FileExcelOutlined,
  PaperClipOutlined,
  SendOutlined,
} from '@ant-design/icons'
import type { UploadFile } from 'antd'
import {
  chatStream,
  executePlan,
  generatePlan,
  generateSummary,
  listModels,
  saveMessages,
  uploadExcel,
  ExecuteResult,
  ExcelPlan,
} from './api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

/* ---------------- 模型选择（全局） ---------------- */

function useModels() {
  const [models, setModels] = useState<Array<{ id: string; name?: string }>>([])
  const [modelId, setModelId] = useState('')
  const [modelError, setModelError] = useState('')

  useEffect(() => {
    listModels()
      .then((list) => {
        const enabled = list.filter((m) => m.disabled !== true)
        setModels(enabled)
        if (enabled.length > 0) setModelId(enabled[0].id)
      })
      .catch((e) => setModelError(`模型列表获取失败: ${(e as Error).message}`))
  }, [])

  return { models, modelId, setModelId, modelError }
}

function ModelSelect({
  models,
  modelId,
  setModelId,
  modelError,
}: {
  models: Array<{ id: string; name?: string }>
  modelId: string
  setModelId: (v: string) => void
  modelError: string
}) {
  if (modelError) return <Alert type="error" showIcon message={modelError} style={{ marginBottom: 12 }} />
  if (models.length === 0)
    return <Alert type="warning" showIcon message="当前没有可用模型，请稍后重试" style={{ marginBottom: 12 }} />
  return (
    <Select
      style={{ width: 260, marginBottom: 12 }}
      value={modelId || undefined}
      placeholder="选择模型"
      onChange={setModelId}
      options={models.map((m) => ({ value: m.id, label: m.name ?? m.id }))}
    />
  )
}

/* ---------------- F1: 对话 ---------------- */

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

function ChatPanel({ models, modelId, setModelId, modelError }: ReturnType<typeof useModels>) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const convId = useRef<string>(crypto.randomUUID())
  const boxRef = useRef<HTMLDivElement>(null)

  const scrollBottom = () =>
    requestAnimationFrame(() => {
      if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
    })

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    if (!modelId) return message.warning('请先选择模型')
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setLoading(true)
    try {
      const history = messages.slice(-20)
      const full = await chatStream(text, history, modelId, (delta) => {
        setMessages((m) => {
          const copy = [...m]
          const last = copy[copy.length - 1]
          copy[copy.length - 1] = { ...last, content: last.content + delta }
          return copy
        })
        scrollBottom()
      })
      // 持久化到后端
      await saveMessages(convId.current, text, full)
    } catch (e) {
      setMessages((m) => {
        const copy = [...m]
        copy[copy.length - 1] = {
          role: 'assistant',
          content: `⚠️ 出错了：${(e as Error).message}`,
        }
        return copy
      })
    } finally {
      setLoading(false)
      scrollBottom()
    }
  }

  return (
    <div>
      <ModelSelect models={models} modelId={modelId} setModelId={setModelId} modelError={modelError} />
      <div className="chat-box" ref={boxRef}>
        {messages.length === 0 && (
          <Text type="secondary">开始和 AI 对话吧（免密钥，云端模型直连）。</Text>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.content || (m.role === 'assistant' ? <Spin size="small" /> : '')}</div>
          </div>
        ))}
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input
          placeholder="输入消息，Enter 发送"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={send}
          disabled={loading}
        />
        <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading}>
          发送
        </Button>
      </Space.Compact>
    </div>
  )
}

/* ---------------- F2: Excel 汇总 ---------------- */

function ExcelPanel({ models, modelId, setModelId, modelError }: ReturnType<typeof useModels>) {
  const [files, setFiles] = useState<UploadFile[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState('')
  const [result, setResult] = useState<ExecuteResult | null>(null)
  const [summary, setSummary] = useState('')
  const [ambiguities, setAmbiguities] = useState<string[] | null>(null)
  const [planDesc, setPlanDesc] = useState('')
  const [error, setError] = useState('')

  const run = async () => {
    if (files.length === 0) return message.warning('请先上传 Excel/CSV 文件')
    if (!query.trim()) return message.warning('请描述汇总需求')
    if (!modelId) return message.warning('请先选择模型')
    setLoading(true)
    setError('')
    setResult(null)
    setSummary('')
    setAmbiguities(null)
    setPlanDesc('')
    try {
      // 1. 上传解析
      setStep('正在上传并解析文件…')
      const list = files.map((f) => f.originFileObj as File).filter(Boolean)
      const { task_id, profiles } = await uploadExcel(list)

      // 2. 云 LLM 生成计划
      setStep('AI 正在理解数据并生成处理计划…')
      const plan: ExcelPlan = await generatePlan(profiles, query, modelId)

      // 3. 需求不明确 → 追问
      if (plan.ambiguities && plan.ambiguities.length > 0) {
        setAmbiguities(plan.ambiguities)
        setPlanDesc(plan.plan_desc ?? '')
        return
      }
      setPlanDesc(plan.plan_desc ?? '')

      // 4. 后端执行
      setStep('正在执行数据汇总…')
      const execResult = await executePlan(task_id, query, plan)

      // 5. 云 LLM 生成总结
      setStep('正在生成结果总结…')
      const summaryText = await generateSummary(execResult, query, modelId)

      setResult(execResult)
      setSummary(summaryText)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
      setStep('')
    }
  }

  return (
    <div>
      <ModelSelect models={models} modelId={modelId} setModelId={setModelId} modelError={modelError} />
      <Upload.Dragger
        multiple
        accept=".xlsx,.xls,.csv"
        maxCount={10}
        fileList={files}
        onChange={({ fileList }) => setFiles(fileList)}
        beforeUpload={() => false}
      >
        <p className="ant-upload-drag-icon">
          <FileExcelOutlined style={{ color: '#1f6fb2', fontSize: 42 }} />
        </p>
        <p className="ant-upload-text">点击或拖拽上传 Excel/CSV 文件（支持多个）</p>
        <p className="ant-upload-hint">支持 .xlsx / .xls / .csv，单文件不超过 50MB</p>
      </Upload.Dragger>

      <TextArea
        rows={2}
        style={{ marginTop: 12 }}
        placeholder="描述你的汇总需求，例如：把两个表按订单号合并，统计每个地区的销售额合计"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <Button
        type="primary"
        icon={<FileExcelOutlined />}
        onClick={run}
        loading={loading}
        style={{ marginTop: 12 }}
      >
        开始汇总
      </Button>

      {loading && step && (
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          icon={<Spin size="small" />}
          message={step}
        />
      )}

      {error && <Alert style={{ marginTop: 16 }} type="error" showIcon message={error} />}

      {ambiguities && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="需求需要澄清"
          description={
            <>
              {planDesc && <Paragraph>{planDesc}</Paragraph>}
              <ul>
                {ambiguities.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
              <Text type="secondary">请补充说明后重新提交。</Text>
            </>
          }
        />
      )}

      {result && (
        <Card style={{ marginTop: 16 }} size="small" title="汇总完成">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="green">结果 {result.result_rows} 行</Tag>
              <Tag color="blue">
                <PaperClipOutlined /> {result.output_file}
              </Tag>
            </Space>
            {summary && <Paragraph>{summary}</Paragraph>}
            <Button type="primary" icon={<DownloadOutlined />} href={result.download_url}>
              下载汇总结果
            </Button>
          </Space>
        </Card>
      )}
    </div>
  )
}

/* ---------------- App ---------------- */

export default function App() {
  const modelState = useModels()
  return (
    <Card
      title="agent-test 智能助手"
      style={{ marginTop: 16 }}
      styles={{ body: { paddingTop: 8 } }}
    >
      <Tabs
        defaultActiveKey="chat"
        items={[
          { key: 'chat', label: 'AI 对话', children: <ChatPanel {...modelState} /> },
          { key: 'excel', label: 'Excel 汇总', children: <ExcelPanel {...modelState} /> },
        ]}
      />
    </Card>
  )
}
