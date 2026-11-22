import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export type ReviewGroup = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  分组编号: string
  关联端点: string
  复核类型: string
  键映射: string
  覆盖差异: string
  覆盖字段: string
  证据状态: string
  组合定义: string
  确认凭据: string
  归并依据: string
  补采依据: string
  待补采项: string
}

export type ReviewTodo = {
  id: number
  status: string
  待办编号: string
  复核分组: number
  关联端点: string
  复核类型: string
  覆盖差异: string
  确认凭据: string
  证据状态: string
  审核结论: string
  已确认字段: string
  落库版本: string
}

export type ReviewReport = {
  id: number
  报告编号: string
  评估范围: string
  复核类型: string
  覆盖差异: string
  证据状态: string
  待审证据: string
  改进事项: string
  status: string
  审核结论?: string
}

export type ReviewEvidence = {
  id: number
  证据编号: string
  关联端点: string
  证据字段: string
  证据类型: string
  来源样本: string
  旧键引用: string
  样本原值: string
  采集状态: string
  采集依据: string
}

export type ReviewVersion = {
  id: number
  版本编号: string
  数据来源: string
  行数统计: number
  Schema摘要: string
  依赖版本: string
  创建原因: string
  status: string
  映射定义?: string
  确认凭据?: string
}

export type ReviewWorkspace = {
  endpoint: string
  diffs: EntryRow[]
  evidence: ReviewEvidence[]
  groups: ReviewGroup[]
  todos: ReviewTodo[]
  reports: ReviewReport[]
  versions: ReviewVersion[]
  confirmed_fields: string[]
}

export type DiffReviewBatchResult = {
  ok: boolean
  message: string
  credentials?: string
  groups: ReviewGroup[]
  problems: string[]
}

export type ConfirmBatchResult = {
  ok: boolean
  message: string
  results: Record<string, unknown>[]
  confirmed_fields: string[]
}

export async function reviewWorkspace(endpoint?: string): Promise<ReviewWorkspace> {
  const query = endpoint ? `?${new URLSearchParams({ endpoint }).toString()}` : ''
  const response = await request(`/api/schema_diff/review/workspace${query}`)
  if (!response.ok) throw new Error('差异复核工作台读取失败')
  return await response.json()
}

export async function reviewDiffBatch(diffIds: number[]): Promise<DiffReviewBatchResult> {
  const response = await request('/api/schema_diff/review/batch', {
    method: 'POST',
    body: JSON.stringify({ diff_ids: diffIds }),
  })
  return await response.json()
}

export async function confirmTodoBatch(todoIds: number[]): Promise<ConfirmBatchResult> {
  const response = await request('/api/diff_confirmation/batch', {
    method: 'POST',
    body: JSON.stringify({ todo_ids: todoIds }),
  })
  return await response.json()
}

export async function addReviewEvidence(payload: {
  endpoint: string
  field: string
  sample: string
  old_keys: string
  source: string
}): Promise<{ ok: boolean; message: string; group_id: number }> {
  const response = await request('/api/diff_evidence/review', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await response.json()
}
