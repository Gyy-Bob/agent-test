import { useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Input,
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
import { chatStream, summarizeExcel, ExcelResult } from './api'

const { Text, Paragraph } = Typography
const { TextArea } = Input

/* ---------------- F1: 对话 ---------------- */

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

function ChatPanel() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const convId = useRef<string | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  const scrollBottom = () =>
    requestAnimationFrame(() => {
      if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
    })

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setLoading(true)
    try {
      await chatStream(
        text,
        convId.current,
        (delta) => {
          setMessages((m) => {
            const copy = [...m]
            const last = copy[copy.length - 1]
            copy[copy.length - 1] = { ...last, content: last.content + delta }
            return copy
          })
          scrollBottom()
        },
        (id) => {
          convId.current = id
        },
      )
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
      <div className="chat-box" ref={boxRef}>
        {messages.length === 0 && (
          <Text type="secondary">开始和 AI 对话吧。上方显示会话 ID，可用于多轮上下文。</Text>
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

function ExcelPanel() {
  const [files, setFiles] = useState<UploadFile[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ExcelResult | null>(null)
  const [error, setError] = useState('')

  const run = async () => {
    if (files.length === 0) return message.warning('请先上传 Excel/CSV 文件')
    if (!query.trim()) return message.warning('请描述汇总需求')
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const list = files.map((f) => f.originFileObj as File).filter(Boolean)
      setResult(await summarizeExcel(list, query))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
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

      {loading && (
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          icon={<Spin size="small" />}
          message="正在解析文件并生成处理计划…"
        />
      )}

      {error && (
        <Alert style={{ marginTop: 16 }} type="error" showIcon message={error} />
      )}

      {result?.status === 'need_clarification' && (
        <Alert
          style={{ marginTop: 16 }}
          type="warning"
          showIcon
          message="需求需要澄清"
          description={
            <>
              {result.plan_desc && <Paragraph>{result.plan_desc}</Paragraph>}
              <ul>
                {result.ambiguities?.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
              <Text type="secondary">请补充说明后重新提交。</Text>
            </>
          }
        />
      )}

      {result?.status === 'done' && (
        <Card style={{ marginTop: 16 }} size="small" title="汇总完成">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="green">结果 {result.result_rows} 行</Tag>
              <Tag color="blue">
                <PaperClipOutlined /> {result.output_file}
              </Tag>
            </Space>
            <Paragraph>{result.summary}</Paragraph>
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
  return (
    <Card
      title="agent-test 智能助手"
      style={{ marginTop: 16 }}
      styles={{ body: { paddingTop: 8 } }}
    >
      <Tabs
        defaultActiveKey="chat"
        items={[
          { key: 'chat', label: 'AI 对话', children: <ChatPanel /> },
          { key: 'excel', label: 'Excel 汇总', children: <ExcelPanel /> },
        ]}
      />
    </Card>
  )
}
