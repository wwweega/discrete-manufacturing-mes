<script setup>
/**
 * 工序报工。
 *
 * 重点演示**幂等控制**：页面自动生成 Idempotency-Key，
 * 并提供「重复提交一次」按钮 —— 后端会回放首次结果且不会产生第二笔数据，
 * 这是简历中「工单状态机流转加事务与幂等控制，防止重复报工产生脏数据」的可验证入口。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { masterApi, orderApi } from '../api/modules'
import { ORDER_STATUS, OP_STATUS, pct } from '../utils/format'
import StatusTag from '../components/StatusTag.vue'

const orders = ref([])
const master = ref(null)
const detail = ref(null)
const error = ref('')
const message = ref('')
const result = ref(null)
const lastKey = ref('')
const submitting = ref(false)

const form = reactive({ operation_id: '', qty_good: 50, qty_defect: 0, employee_id: '', shift_id: '', measurements: '' })

const canReport = computed(() => detail.value && detail.value.order.status === 'IN_PROGRESS')

const newKey = () => `ui-${Date.now()}-${Math.floor(Math.random() * 100000)}`

async function loadAll() {
  master.value = await masterApi.all()
  const list = await orderApi.list({ status: 'IN_PROGRESS' })
  orders.value = list.items
  if (orders.value.length && !detail.value) await selectOrder(orders.value[0].id)
}

async function selectOrder(id) {
  detail.value = await orderApi.detail(id)
  result.value = null
  message.value = ''
}

async function submit(reuseKey = false) {
  error.value = ''
  message.value = ''
  submitting.value = true
  try {
    const key = reuseKey ? lastKey.value : newKey()
    lastKey.value = key
    const measurements = form.measurements
      ? form.measurements.split(',').map((v) => Number(v.trim())).filter((v) => !Number.isNaN(v))
      : []
    result.value = await orderApi.report(
      detail.value.order.id,
      {
        operation_id: Number(form.operation_id),
        qty_good: Number(form.qty_good),
        qty_defect: Number(form.qty_defect || 0),
        employee_id: form.employee_id ? Number(form.employee_id) : null,
        shift_id: form.shift_id ? Number(form.shift_id) : null,
        measurements
      },
      key
    )
    message.value = result.value.duplicated
      ? `重复提交已被幂等拦截，返回首次报工单号 ${result.value.report_no}`
      : `报工成功：${result.value.report_no}`
    detail.value = await orderApi.detail(detail.value.order.id)
  } catch (e) {
    error.value = e.message
  } finally {
    submitting.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert" :class="result?.duplicated ? 'alert-info' : 'alert-success'">{{ message }}</div>

    <div class="card">
      <div class="card-head">
        <h2>工序报工</h2>
        <select @change="(e) => selectOrder(Number(e.target.value))">
          <option v-for="o in orders" :key="o.id" :value="o.id">{{ o.order_no }}</option>
        </select>
      </div>

      <div v-if="!canReport" class="alert alert-info">
        当前工单状态为
        <StatusTag :map="ORDER_STATUS" :value="detail?.order?.status" />，
        仅 <b>IN_PROGRESS</b> 工单允许报工，请先在工单页面下达并开工。
      </div>

      <div v-if="detail" class="toolbar">
        <select v-model="form.operation_id">
          <option value="">选择工序</option>
          <option v-for="op in detail.operations" :key="op.id" :value="op.id">
            {{ op.operation_code }} {{ op.operation_name }}（剩余 {{ op.plan_qty - op.done_qty }}）
          </option>
        </select>
        <input v-model="form.qty_good" type="number" style="width: 100px" placeholder="合格数" />
        <input v-model="form.qty_defect" type="number" style="width: 100px" placeholder="不良数" />
        <select v-model="form.employee_id">
          <option value="">选择操作员</option>
          <option v-for="e in master?.employees || []" :key="e.id" :value="e.id">{{ e.emp_no }} {{ e.name }}</option>
        </select>
        <select v-model="form.shift_id">
          <option value="">选择班次</option>
          <option v-for="s in master?.shifts || []" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
        <input v-model="form.measurements" style="width: 220px" placeholder="SPC样本（逗号分隔，可空）" />
        <button class="btn" :disabled="!form.operation_id || submitting" @click="submit(false)">提交报工</button>
        <button class="btn ghost" :disabled="!lastKey || submitting" @click="submit(true)">
          用同一幂等键重复提交
        </button>
      </div>

      <div class="small muted">
        当前幂等键：<code>{{ lastKey || '提交后生成' }}</code>
        —— 重复提交同一键不会新增数据，而是回放首次结果。
      </div>
    </div>

    <div v-if="result" class="card">
      <div class="card-head"><h2>报工结果</h2></div>
      <div class="grid grid-4">
        <div><div class="muted small">报工单号</div><div>{{ result.report_no }}</div></div>
        <div><div class="muted small">工序完成量</div><div>{{ result.operation_done_qty }}</div></div>
        <div><div class="muted small">工单进度</div><div>{{ pct(result.order_progress, 1) }}</div></div>
        <div><div class="muted small">自动完工</div><div>{{ result.auto_completed ? '是' : '否' }}</div></div>
      </div>
      <div v-if="result.inventory_flows?.length" style="margin-top: 12px">
        <div class="muted small" style="margin-bottom: 4px">本次报工触发的库存扣减（库存联动）：</div>
        <table>
          <thead><tr><th>流水号</th><th>物料ID</th><th>扣减量</th><th>扣后结存</th></tr></thead>
          <tbody>
            <tr v-for="f in result.inventory_flows" :key="f.tx_no">
              <td>{{ f.tx_no }}</td><td>{{ f.material_id }}</td><td>{{ f.qty }}</td><td>{{ f.balance_after }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="result.spc" class="alert alert-info" style="margin-top: 12px">
        SPC 子组 #{{ result.spc.subgroup_no }} 均值 {{ result.spc.mean_value }}，
        {{ result.spc.is_out_of_control ? `触发判异（${result.spc.alarm_rules}），已生成质检单 ${result.spc.inspection_task_no}` : '未触发判异' }}
      </div>
    </div>

    <div v-if="detail" class="card">
      <div class="card-head"><h2>工序进度</h2></div>
      <table>
        <thead>
          <tr><th>序号</th><th>工序</th><th>状态</th><th>计划</th><th>完成</th><th>合格</th><th>不良</th></tr>
        </thead>
        <tbody>
          <tr v-for="op in detail.operations" :key="op.id">
            <td>{{ op.seq }}</td>
            <td>{{ op.operation_code }} {{ op.operation_name }}</td>
            <td><StatusTag :map="OP_STATUS" :value="op.status" /></td>
            <td>{{ op.plan_qty }}</td>
            <td>{{ op.done_qty }}</td>
            <td>{{ op.good_qty }}</td>
            <td>{{ op.defect_qty }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
