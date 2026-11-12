// 临时诊断脚本：验证云 SDK 模型列表与对话调用
const { createWorkBuddyCloud } = require('@tencent-ai/workbuddy-cloud-sdk')

const cloud = createWorkBuddyCloud({
  endpoint: 'https://agent-test-assistant.app.workbuddy.host',
  publishableKey: 'wbpk_d8GkhGNq76eFLBSdqwgsmG_KIavXuYvwM2gfIWgPmz5YHKz0UPyEsa2',
})

async function main() {
  try {
    const models = await cloud.llm.models.list()
    console.log('models.list OK, 数量:', models.length)
    const enabled = models.filter((m) => m.disabled !== true)
    if (enabled.length === 0) {
      console.log('没有可用模型！')
      return
    }
    const model = enabled[0]
    console.log('使用模型:', model.id)

    let full = ''
    for await (const chunk of cloud.llm.chat.completions.create({
      model: model.id,
      messages: [
        { role: 'system', content: '你是测试助手，用中文简短回答。' },
        { role: 'user', content: '回复"测试成功"四个字' },
      ],
      stream: true,
    })) {
      const d = chunk.choices?.[0]?.delta?.content
      if (d) full += d
    }
    console.log('对话调用 OK, 回复:', full)
  } catch (e) {
    console.error('调用失败:', e.name, e.message)
    if (e.error) console.error('error detail:', JSON.stringify(e.error))
    if (e.requestId) console.error('requestId:', e.requestId)
  }
}

main()
