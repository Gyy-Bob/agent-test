# agent-test 智能助手

AI 大模型对话 + Excel 导入汇总生成新 Excel 的云端 Agent。

- **功能 1（AI 对话）**：多轮流式对话，OpenAI 兼容协议，可切换 DeepSeek / 通义千问 / GLM / GPT
- **功能 2（Excel 汇总）**：上传 1~N 个 Excel/CSV，用自然语言描述需求，Agent 自动生成处理计划并输出一份新的 Excel（含汇总结果、数据来源说明、处理日志三个 sheet）
- **技术栈**：后端 Python + FastAPI + pandas；前端 React 18 + TypeScript + Vite + Ant Design

## 目录结构

```
backend/
  app/
    main.py                 # FastAPI 入口
    core/config.py          # 配置（.env）
    core/llm.py             # OpenAI 兼容 LLM 客户端（流式/非流式）
    db/models.py            # 会话/消息/Excel任务 表模型
    api/routes_chat.py      # F1 对话接口（SSE 流式）
    api/routes_excel.py     # F2 上传汇总/下载接口
    services/excel_service.py  # Excel 解析、计划执行、结果生成
    skills/                 # Agent 技能层
      router.py             # 意图路由
      excel_summary/skill.py   # excel_summary 技能（解析→计划→执行→交付）
frontend/
  src/App.tsx               # 对话 + Excel 汇总界面
  src/api.ts                # SSE 流式调用封装
```

## 本地启动

### 1. 后端（首次）

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
copy .env.example .env      # 编辑 .env 填入 LLM_API_KEY
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

### 2. 前端（首次）

```bash
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
```

打开 http://localhost:5173 即可使用。

## 配置说明（backend/.env）

| 变量 | 说明 | 示例 |
|---|---|---|
| LLM_API_KEY | 大模型 API Key（必填） | sk-xxxx |
| LLM_BASE_URL | OpenAI 兼容地址 | https://api.deepseek.com/v1 |
| LLM_MODEL | 模型名 | deepseek-chat / qwen-plus |
| DATABASE_URL | 数据库连接 | 默认 SQLite，上云换 PostgreSQL |

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查（含 LLM 配置状态） |
| POST | /api/chat/stream | 流式对话（SSE） |
| GET | /api/chat/conversations | 会话列表 |
| POST | /api/excel/summarize | 上传文件 + 需求 → 汇总（表单：query + files[]） |
| GET | /api/excel/download/{file} | 下载生成的 Excel |
| GET | /api/excel/tasks/{id} | 查询任务状态 |

## 云端部署路线

1. 本地开发（当前）：SQLite + 本地磁盘存储
2. 上云：.env 切换 PostgreSQL；文件存储改造为 COS/OSS；Docker Compose 部署 + Nginx + HTTPS
