<template>
  <section class="page" data-testid="diff-review">
    <header class="page-head">
      <div>
        <h2>差异复核台</h2>
        <p class="page-desc">
          批量勾选Schema差异，按字段差异的实际引用关系归并复核分组：参与同一键映射的字段合成关联组，
          可单列验证的差异单独成组；治理报告按分组登记待审证据，确认结果同步差异确认待办并落库数据版本。
        </p>
      </div>
      <div class="page-actions">
        <input
          v-model="endpoint"
          class="review-input"
          data-testid="review-endpoint"
          placeholder="按端点筛选，如 ENDP-ORD-0006"
          @change="reload"
        />
        <button class="btn" type="button" data-testid="review-refresh" @click="reload">刷新</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">选中差异</span>
        <strong class="stat-value" data-testid="selected-count">{{ selected.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">复核分组</span>
        <strong class="stat-value" data-testid="group-count">{{ workspace?.groups.length ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待确认待办</span>
        <strong class="stat-value" data-testid="todo-count">{{ openTodos.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">已确认字段</span>
        <strong class="stat-value" data-testid="confirmed-fields">
          {{ (workspace?.confirmed_fields ?? []).join('、') || '—' }}
        </strong>
      </article>
    </div>

    <p v-if="message" class="review-message" data-testid="review-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="review-error">{{ errorMessage }}</p>

    <section class="review-block">
      <header class="review-block-head">
        <h3>可选差异（一次提交选中变化）</h3>
        <div class="page-actions">
          <button class="btn" type="button" data-testid="select-related" @click="selectRelated">
            选中关联键差异
          </button>
          <button class="btn" type="button" data-testid="select-standalone" @click="selectStandalone">
            选中独立新增列
          </button>
          <button
            class="btn primary"
            type="button"
            data-testid="submit-review"
            :disabled="!selected.length || submitting"
            @click="submitReview"
          >
            {{ submitting ? '归并中…' : '提交选中差异' }}
          </button>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 44px">选择</th>
            <th>记录编号</th>
            <th>关联端点</th>
            <th>变更字段</th>
            <th>旧定义</th>
            <th>新定义</th>
            <th>引用差异</th>
            <th>键映射</th>
            <th>当前状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="diff in workspace?.diffs ?? []"
            :key="String(diff.id)"
            :data-testid="`diff-row-${diff.id}`"
          >
            <td>
              <input
                type="checkbox"
                :value="Number(diff.id)"
                :checked="selected.includes(Number(diff.id))"
                :data-testid="`diff-pick-${diff.id}`"
                @change="toggle(Number(diff.id))"
              />
            </td>
            <td>{{ diff['记录编号'] }}</td>
            <td>{{ diff['关联端点'] }}</td>
            <td>{{ diff['变更字段'] }}</td>
            <td>{{ diff['旧定义'] || '—' }}</td>
            <td>{{ diff['新定义'] }}</td>
            <td>{{ diff['引用差异'] || '—' }}</td>
            <td>{{ diff['键映射'] || '—' }}</td>
            <td>{{ diff.status }}</td>
          </tr>
          <tr v-if="!(workspace?.diffs ?? []).length">
            <td colspan="9" class="empty-state">当前端点没有待复核差异</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="review-block">
      <h3>复核分组</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>分组编号</th>
            <th>复核类型</th>
            <th>覆盖差异</th>
            <th>键映射</th>
            <th>证据状态</th>
            <th>组合定义</th>
            <th>确认凭据</th>
            <th>归并/补采依据</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="group in workspace?.groups ?? []"
            :key="group.id"
            :data-testid="`group-row-${group.id}`"
            :data-review-type="group.复核类型"
          >
            <td>{{ group.分组编号 }}</td>
            <td>{{ group.复核类型 }}</td>
            <td>{{ group.覆盖差异 }}</td>
            <td>{{ group.键映射 || '—' }}</td>
            <td data-testid="group-evidence">{{ group.证据状态 }}</td>
            <td>{{ group.组合定义 || '—' }}</td>
            <td>{{ group.确认凭据 }}</td>
            <td class="review-note">
              <div>{{ group.归并依据 }}</div>
              <div>{{ group.补采依据 }}</div>
            </td>
            <td>{{ group.status }}</td>
            <td>
              <button
                class="link"
                type="button"
                :data-testid="`group-resubmit-${group.id}`"
                @click="resubmit(group.id)"
              >
                重提核验
              </button>
            </td>
          </tr>
          <tr v-if="!(workspace?.groups ?? []).length">
            <td colspan="10" class="empty-state">尚未归并复核分组</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="review-block">
      <header class="review-block-head">
        <h3>治理报告（按分组登记待审核的采集证据）</h3>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>报告编号</th>
            <th>复核类型</th>
            <th>覆盖差异</th>
            <th>待审证据</th>
            <th>证据状态</th>
            <th>改进事项</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="report in workspace?.reports ?? []"
            :key="report.id"
            :data-testid="`report-row-${report.报告编号}`"
          >
            <td>{{ report.报告编号 }}</td>
            <td>{{ report.复核类型 }}</td>
            <td>{{ report.覆盖差异 }}</td>
            <td class="review-note">{{ report.待审证据 }}</td>
            <td>{{ report.证据状态 }}</td>
            <td>{{ report.改进事项 }}</td>
            <td>{{ report.status }}</td>
          </tr>
          <tr v-if="!(workspace?.reports ?? []).length">
            <td colspan="7" class="empty-state">尚未生成复核治理报告</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="review-block">
      <header class="review-block-head">
        <h3>差异确认待办</h3>
        <div class="page-actions">
          <button
            class="btn primary"
            type="button"
            data-testid="confirm-batch"
            :disabled="!pickedTodos.length || confirming"
            @click="confirmPicked"
          >
            {{ confirming ? '确认中…' : '确认选中待办' }}
          </button>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th style="width: 44px">选择</th>
            <th>待办编号</th>
            <th>复核分组</th>
            <th>复核类型</th>
            <th>覆盖差异</th>
            <th>确认凭据</th>
            <th>证据状态</th>
            <th>审核结论</th>
            <th>已确认字段</th>
            <th>落库版本</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="todo in workspace?.todos ?? []"
            :key="todo.id"
            :data-testid="`todo-row-${todo.待办编号}`"
            :data-status="todo.status"
          >
            <td>
              <input
                type="checkbox"
                :checked="pickedTodos.includes(todo.id)"
                :data-testid="`todo-pick-${todo.id}`"
                @change="toggleTodo(todo.id)"
              />
            </td>
            <td>{{ todo.待办编号 }}</td>
            <td>{{ todo.复核分组 }}</td>
            <td>{{ todo.复核类型 }}</td>
            <td>{{ todo.覆盖差异 }}</td>
            <td>{{ todo.确认凭据 }}</td>
            <td>{{ todo.证据状态 }}</td>
            <td>{{ todo.审核结论 }}</td>
            <td>{{ todo.已确认字段 || '—' }}</td>
            <td>{{ todo.落库版本 || '—' }}</td>
            <td>{{ todo.status }}</td>
          </tr>
          <tr v-if="!(workspace?.todos ?? []).length">
            <td colspan="11" class="empty-state">尚未生成差异确认待办</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="review-block">
      <header class="review-block-head">
        <h3>采集证据与样本原值（补采入口）</h3>
      </header>
      <form class="analysis-form" @submit.prevent="submitEvidence">
        <label>
          <span>关联端点</span>
          <input v-model="evidenceForm.endpoint" data-testid="evidence-endpoint" required />
        </label>
        <label>
          <span>证据字段</span>
          <input v-model="evidenceForm.field" data-testid="evidence-field" placeholder="item_key" required />
        </label>
        <label>
          <span>样本原值</span>
          <input v-model="evidenceForm.sample" data-testid="evidence-sample" placeholder="10001-1" />
        </label>
        <label>
          <span>覆盖旧键</span>
          <input v-model="evidenceForm.old_keys" data-testid="evidence-old-keys" placeholder="order_id,line_no" />
        </label>
        <label>
          <span>来源样本</span>
          <input v-model="evidenceForm.source" data-testid="evidence-source" />
        </label>
        <button class="btn primary" type="submit" data-testid="submit-evidence">登记补采证据</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>证据编号</th>
            <th>证据字段</th>
            <th>证据类型</th>
            <th>旧键引用</th>
            <th>样本原值</th>
            <th>来源样本</th>
            <th>采集状态</th>
            <th>采集依据</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in workspace?.evidence ?? []"
            :key="item.id"
            :data-testid="`evidence-row-${item.证据字段}`"
          >
            <td>{{ item.证据编号 }}</td>
            <td>{{ item.证据字段 }}</td>
            <td>{{ item.证据类型 }}</td>
            <td>{{ item.旧键引用 || '—' }}</td>
            <td>{{ item.样本原值 || '—' }}</td>
            <td class="review-note">{{ item.来源样本 }}</td>
            <td>{{ item.采集状态 }}</td>
            <td class="review-note">{{ item.采集依据 }}</td>
          </tr>
          <tr v-if="!(workspace?.evidence ?? []).length">
            <td colspan="8" class="empty-state">当前端点没有登记采集证据</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="review-block">
      <h3>数据版本（按已审核的来源和映射落库）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>版本编号</th>
            <th>数据来源</th>
            <th>行数统计</th>
            <th>映射定义</th>
            <th>依赖版本</th>
            <th>创建原因</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="version in workspace?.versions ?? []"
            :key="version.id"
            :data-testid="`version-row-${version.版本编号}`"
          >
            <td>{{ version.版本编号 }}</td>
            <td>{{ version.数据来源 }}</td>
            <td>{{ version.行数统计 }}</td>
            <td>{{ version.映射定义 || version.Schema摘要 }}</td>
            <td>{{ version.依赖版本 }}</td>
            <td class="review-note">{{ version.创建原因 }}</td>
            <td>{{ version.status }}</td>
          </tr>
          <tr v-if="!(workspace?.versions ?? []).length">
            <td colspan="7" class="empty-state">确认落库后在此回查数据版本</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  addReviewEvidence,
  confirmTodoBatch,
  reviewDiffBatch,
  reviewWorkspace,
  runAction,
} from '@/api/backend-service'
import type { ReviewWorkspace } from '@/api/backend-service'

const endpoint = ref('')
const workspace = ref<ReviewWorkspace | null>(null)
const selected = ref<number[]>([])
const pickedTodos = ref<number[]>([])
const message = ref('')
const errorMessage = ref('')
const submitting = ref(false)
const confirming = ref(false)
const evidenceForm = ref({ endpoint: '', field: '', sample: '', old_keys: '', source: '' })

const openTodos = computed(
  () => (workspace.value?.todos ?? []).filter((todo) => todo.status !== '已确认' && todo.status !== '已作废'),
)

function toggle(id: number) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((item) => item !== id)
    : [...selected.value, id]
}

function toggleTodo(id: number) {
  pickedTodos.value = pickedTodos.value.includes(id)
    ? pickedTodos.value.filter((item) => item !== id)
    : [...pickedTodos.value, id]
}

function selectRelated() {
  const related = (workspace.value?.diffs ?? []).filter((diff) => Boolean(diff['键映射']))
  selected.value = Array.from(new Set([...selected.value, ...related.map((diff) => Number(diff.id))]))
}

function selectStandalone() {
  const relatedEndpoints = new Set(
    (workspace.value?.diffs ?? [])
      .filter((diff) => Boolean(diff['键映射']))
      .map((diff) => String(diff['关联端点'])),
  )
  const standalone = (workspace.value?.diffs ?? []).filter(
    (diff) =>
      !diff['键映射'] &&
      !String(diff['引用差异'] ?? '').trim() &&
      (!relatedEndpoints.size || relatedEndpoints.has(String(diff['关联端点']))),
  )
  selected.value = Array.from(new Set([...selected.value, ...standalone.map((diff) => Number(diff.id))]))
}

async function reload() {
  errorMessage.value = ''
  try {
    workspace.value = await reviewWorkspace(endpoint.value.trim() || undefined)
    if (!evidenceForm.value.endpoint) {
      const first = workspace.value.diffs[0]
      evidenceForm.value.endpoint = endpoint.value.trim() || (first ? String(first['关联端点']) : '')
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复核工作台读取失败'
  }
}

async function submitReview() {
  submitting.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await reviewDiffBatch(selected.value)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    selected.value = []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '差异归并失败'
  } finally {
    submitting.value = false
  }
}

async function resubmit(groupId: number) {
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await runAction('diff_review_group', groupId, '重提核验')
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重提核验失败'
  }
}

async function confirmPicked() {
  confirming.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await confirmTodoBatch(pickedTodos.value)
    message.value = result.message
    pickedTodos.value = []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量确认失败'
  } finally {
    confirming.value = false
  }
}

async function submitEvidence() {
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await addReviewEvidence(evidenceForm.value)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    evidenceForm.value = { ...evidenceForm.value, field: '', sample: '', old_keys: '', source: '' }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补采证据登记失败'
  }
}

onMounted(async () => {
  await reload()
  if (!selected.value.length) {
    selectRelated()
    if (endpoint.value.trim() === 'ENDP-ORD-0006') selectStandalone()
  }
  pickedTodos.value = openTodos.value.map((todo) => todo.id)
})
</script>
