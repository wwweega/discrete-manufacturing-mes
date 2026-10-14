<script setup>
/** 质检单：列表、流转（待处理→检验中→合格/不合格→关闭）、录入检验记录。 */
import { onMounted, reactive, ref } from 'vue'
import DataTable from '../components/DataTable.vue'
import StatusTag from '../components/StatusTag.vue'
import { qualityApi } from '../api/modules'
import { QC_STATUS, dateText } from '../utils/format'
import { useAuthStore } from '../store'

const auth = useAuthStore()
const rows = ref([])
const pending = ref(0)
const error = ref('')
const message = ref('')
const filter = reactive({ status: '', source: '' })

const columns = [
  { title: '质检单号', key: 'task_no' },
  { title: '工单号', key: 'order_no' },
  { title: '工序', key: 'operation_name' },
  { title: '来源', key: 'source' },
  { title: '状态', key: 'status' },
  { title: '抽检', key: 'sample_qty' },
  { title: '不良', key: 'defect_qty' },
  { title: '生成原因', key: 'trigger_reason' },
  { title: '操作', key: 'ops', width: '170px' }
]

const SOURCE_TEXT = {
  SPC_ALERT: 'SPC 自动告警',
  MANUAL: '人工报检',
  INCOMING: '来料检验'
}

async function load() {
  try {
    const data = await qualityApi.tasks({ status: filter.status || undefined, source: filter.source || undefined })
    rows.value = data.items
    pending.value = data.pending_count
  } catch (e) {
    error.value = e.message
  }
}

async function move(task, status) {
  try {
    await qualityApi.transition(task.id, { target_status: status })
    message.value = `${task.task_no} 已流转至 ${status}`
    await load()
  } catch (e) {
    error.value = e.message
    message.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>

    <div class="card">
      <div class="card-head">
        <h2>质检单（待处理 {{ pending }} 单）</h2>
        <div class="toolbar" style="margin: 0">
          <select v-model="filter.status" @change="load">
            <option value="">全部状态</option>
            <option v-for="(v, k) in QC_STATUS" :key="k" :value="k">{{ v.label }}</option>
          </select>
          <select v-model="filter.source" @change="load">
            <option value="">全部来源</option>
            <option value="SPC_ALERT">SPC 自动告警</option>
            <option value="MANUAL">人工报检</option>
          </select>
        </div>
      </div>

      <DataTable :columns="columns" :rows="rows">
        <template #cell-status="{ value }"><StatusTag :map="QC_STATUS" :value="value" /></template>
        <template #cell-source="{ value }">
          <span class="tag" :class="value === 'SPC_ALERT' ? 'tag-danger' : 'tag-muted'">
            {{ SOURCE_TEXT[value] || value }}
          </span>
        </template>
        <template #cell-trigger_reason="{ value }">
          <span :title="value">{{ value ? value.slice(0, 34) + (value.length > 34 ? '…' : '') : '—' }}</span>
        </template>
        <template #cell-ops="{ row }">
          <template v-if="auth.can('quality:handle')">
            <a v-if="row.status === 'PENDING'" href="javascript:void(0)" @click="move(row, 'TESTING')">开始检验</a>
            <span v-if="row.status === 'TESTING'" style="white-space: nowrap">
              <a href="javascript:void(0)" @click="move(row, 'PASSED')">合格</a>
              <a href="javascript:void(0)" style="margin-left: 8px" @click="move(row, 'FAILED')">不合格</a>
            </span>
            <a v-if="['PASSED', 'FAILED'].includes(row.status)" href="javascript:void(0)" @click="move(row, 'CLOSED')">关闭</a>
          </template>
          <span v-else class="muted small">无操作权限</span>
        </template>
      </DataTable>
    </div>
  </div>
</template>
