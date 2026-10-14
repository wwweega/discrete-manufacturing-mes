<script setup>
/** 工单列表 + 创建 + 状态流转。流转按钮由后端状态机返回的合法目标状态动态渲染。 */
import { computed, onMounted, reactive, ref } from 'vue'
import DataTable from '../components/DataTable.vue'
import StatusTag from '../components/StatusTag.vue'
import { masterApi, orderApi } from '../api/modules'
import { ORDER_STATUS, OP_STATUS, pct } from '../utils/format'
import { useAuthStore } from '../store'

const auth = useAuthStore()

const rows = ref([])
const master = ref(null)
const detail = ref(null)
const error = ref('')
const message = ref('')
const filter = reactive({ status: '', keyword: '' })

const createForm = reactive({ product_id: '', routing_id: '', qty_planned: 200, priority: 5 })
const showCreate = ref(false)

const TRANSITION_LABEL = {
  RELEASED: '下达',
  IN_PROGRESS: '开工',
  PAUSED: '暂停',
  COMPLETED: '完工',
  CANCELLED: '作废'
}

const columns = [
  { title: '工单号', key: 'order_no' },
  { title: '产品', key: 'product_name', width: '180px' },
  { title: '状态', key: 'status' },
  { title: '优先级', key: 'priority' },
  { title: '计划量', key: 'qty_planned' },
  { title: '完成量', key: 'qty_completed' },
  { title: '进度', key: 'progress' },
  { title: '操作', key: 'ops', width: '150px' }
]

const opColumns = [
  { title: '序号', key: 'seq' },
  { title: '工序编码', key: 'operation_code' },
  { title: '工序名称', key: 'operation_name' },
  { title: '状态', key: 'status' },
  { title: '计划量', key: 'plan_qty' },
  { title: '完成量', key: 'done_qty' },
  { title: '合格', key: 'good_qty' },
  { title: '不良', key: 'defect_qty' },
  { title: 'SPC', key: 'spc_enabled' }
]

const products = computed(() => master.value?.products || [])
const routings = computed(() => master.value?.routings || [])

async function loadList() {
  try {
    rows.value = (await orderApi.list({ status: filter.status || undefined, keyword: filter.keyword || undefined })).items
  } catch (e) {
    error.value = e.message
  }
}

async function loadMaster() {
  master.value = await masterApi.all()
}

async function openDetail(id) {
  detail.value = await orderApi.detail(id)
  message.value = ''
}

async function transition(status) {
  try {
    await orderApi.transition(detail.value.order.id, { target_status: status, reason: '前端操作' })
    message.value = `工单已流转至 ${status}`
    detail.value = await orderApi.detail(detail.value.order.id)
    await loadList()
  } catch (e) {
    error.value = e.message
    message.value = ''
  }
}

async function createOrder() {
  try {
    await orderApi.create({
      product_id: Number(createForm.product_id),
      routing_id: Number(createForm.routing_id),
      qty_planned: Number(createForm.qty_planned),
      priority: Number(createForm.priority)
    })
    showCreate.value = false
    message.value = '工单创建成功（草稿状态）'
    await loadList()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  await loadMaster()
  await loadList()
})
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>

    <div class="card">
      <div class="card-head">
        <h2>生产工单</h2>
        <button v-if="auth.can('order:create')" class="btn" @click="showCreate = !showCreate">
          {{ showCreate ? '收起' : '新建工单' }}
        </button>
      </div>

      <div v-if="showCreate" class="card" style="background: #fafbfe">
        <div class="toolbar">
          <select v-model="createForm.product_id">
            <option value="">选择产品</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.code }} {{ p.name }}</option>
          </select>
          <select v-model="createForm.routing_id">
            <option value="">选择工艺路线</option>
            <option v-for="r in routings" :key="r.id" :value="r.id">{{ r.routing_code }} {{ r.routing_name }}</option>
          </select>
          <input v-model="createForm.qty_planned" type="number" style="width: 120px" placeholder="计划产量" />
          <input v-model="createForm.priority" type="number" style="width: 90px" placeholder="优先级" />
          <button class="btn" @click="createOrder">提交</button>
        </div>
        <div class="small muted">提交后自动按工艺路线展开工序、按 BOM 展开物料需求</div>
      </div>

      <div class="toolbar">
        <select v-model="filter.status" @change="loadList">
          <option value="">全部状态</option>
          <option v-for="(v, k) in ORDER_STATUS" :key="k" :value="k">{{ v.label }}</option>
        </select>
        <input v-model="filter.keyword" placeholder="工单号模糊查询" @keyup.enter="loadList" />
        <button class="btn ghost" @click="loadList">查询</button>
      </div>

      <DataTable :columns="columns" :rows="rows">
        <template #cell-status="{ value }"><StatusTag :map="ORDER_STATUS" :value="value" /></template>
        <template #cell-progress="{ value }">
          <div class="progress"><span :style="{ width: `${Math.min(value, 100)}%` }"></span></div>
          <span class="small muted">{{ pct(value, 1) }}</span>
        </template>
        <template #cell-ops="{ row }">
          <a href="javascript:void(0)" @click="openDetail(row.id)">详情</a>
        </template>
      </DataTable>
    </div>

    <div v-if="detail" class="card">
      <div class="card-head">
        <h2>工单详情 · {{ detail.order.order_no }}</h2>
        <div>
          <StatusTag :map="ORDER_STATUS" :value="detail.order.status" />
          <button
            v-for="t in detail.allowed_transitions"
            :key="t"
            class="btn"
            :class="{ danger: t === 'CANCELLED' }"
            style="margin-left: 6px"
            @click="transition(t)"
          >
            {{ TRANSITION_LABEL[t] || t }}
          </button>
        </div>
      </div>

      <div class="grid grid-4" style="margin-bottom: 14px">
        <div>
          <div class="muted small">计划 / 完成</div>
          <div>{{ detail.order.qty_planned }} / {{ detail.order.qty_completed }}</div>
        </div>
        <div>
          <div class="muted small">合格 / 不良</div>
          <div>{{ detail.order.qty_good }} / {{ detail.order.qty_defect }}</div>
        </div>
        <div>
          <div class="muted small">进度</div>
          <div>{{ pct(detail.summary.progress, 1) }}</div>
        </div>
        <div>
          <div class="muted small">良品率</div>
          <div>{{ pct(detail.summary.yield_rate, 1) }}</div>
        </div>
      </div>

      <h2 style="font-size: 13.5px; margin: 6px 0">工序清单</h2>
      <DataTable :columns="opColumns" :rows="detail.operations">
        <template #cell-status="{ value }"><StatusTag :map="OP_STATUS" :value="value" /></template>
        <template #cell-spc_enabled="{ value }">
          <span class="tag" :class="value ? 'tag-primary' : 'tag-muted'">{{ value ? '受控' : '—' }}</span>
        </template>
      </DataTable>

      <h2 style="font-size: 13.5px; margin: 14px 0 6px">物料需求</h2>
      <table>
        <thead>
          <tr><th>物料</th><th>需求总量</th><th>已发</th><th>退料</th><th>单位用量</th></tr>
        </thead>
        <tbody>
          <tr v-for="m in detail.materials" :key="m.id">
            <td>{{ m.material_name || m.material_id }}</td>
            <td>{{ m.qty_required }}</td>
            <td>{{ m.qty_issued }}</td>
            <td>{{ m.qty_returned }}</td>
            <td>{{ m.unit_usage }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
