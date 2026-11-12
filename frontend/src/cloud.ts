import { createWorkBuddyCloud } from '@tencent-ai/workbuddy-cloud-sdk'
import { publicConfig } from './publicConfig'

/** 云服务客户端：LLM 免密钥调用（初始化一次，全应用复用） */
export const cloud = createWorkBuddyCloud({
  endpoint: publicConfig.endpoint,
  publishableKey: publicConfig.publishableKey,
})
