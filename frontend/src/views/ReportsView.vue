<script setup>
/**
 * 8 张统计报表统一入口。
 * 报表目录与数据全部来自后端多表关联 SQL，前端仅按编号渲染表格与关键图表。
 */
import { computed, onMounted, ref } from 'vue'
import DataTable from '../components/DataTable.vue'
import ChartBox from '../components/ChartBox.vue'
import { reportApi } from '../api/modules'
import { num, pct } from '../utils/format'

const catalog = ref([])
const active = ref('work_order_progress')
const payload = ref(null)
const error = ref('')
const days = ref(30)

/** 各报表的列定义与图表开关 */
const VIEW_CONFIG = {
  work_order_progress: {
    columns: [
      { title: '工单号', key: 'order_no' },
      { title: '产品', key: 'product_name' },
      { title: '状态', key: 'status' },
      { title: '计划量', key: 'qty_planned' },
      { title: '完成量', key: 'qty_completed' },
      { title: '合格', key: 'qty_good' },
      { title: '不良', key: 'qty_defect' },
      { title: '进度', key: 'progress' }
    ],
    chart: 'progress'
  },
  yield_rate: {
    columns: [
      { title: '产品编码', key: 'product_code' },
      { title: '产品', key: 'product_name' },
      { title: '工单数', key: 'orders' },
      { title: '完成量', key: 'qty_completed' },
      { title: '合格', key: 'qty_good' },
      { title: '不良', key: 'qty_defect' },
      { title: '良品率', key: 'yield_rate' }
    ],
    chart: 'yield'
  },
  equipment_oee: {
    columns: [
      { title: '设备编码', key: 'equipment_code' },
      { title: '设备', key: 'equipment_name' },
      { title: '状态', key: 'status' },
      { title: '运行秒', key: 'run_seconds' },
      { title: '产出', key: 'output_qty' },
      { title: '稼动率', key: 'availability' }
    ],
    chart: 'oee'
  },
  output_daily: {
    columns: [
      { title: '日期', key: 'stat_date' },
      { title: '合格数', key: 'qty_good' },
      { title: '不良数', key: 'qty_defect' },
      { title: '报工次数', key: 'reports' },
      { title: '工时(h)', key: 'labor_hour' },
      { title: '良品率', key: 'yield_rate' }
    ],
    chart: 'output'
  },
  operation_efficiency: {
    columns: [
      { title: '工单号', key: 'order_no' },
      { title: '工序', key: 'operation_name' },
      { title: '设备', key: 'equipment_name' },
      { title: '完成量', key: 'done_qty' },
      { title: '标准工时(s)', key: 'std_seconds' },
      { title: '实际工时(s)', key: 'actual_seconds' },
      { title: '效率', key: 'efficiency' }
    ],
    chart: null
  },
  defect_pareto: {
    columns: [
      { title: '不良代码', key: 'defect_code' },
      { title: '不良名称', key: 'defect_name' },
      { title: '类别', key: 'category' },
      { title: '数量', key: 'qty' },
      { title: '占比', key: 'ratio' },
      { title: '累计占比', key: 'cumulative_ratio' }
    ],
    chart: 'pareto'
  },
  inventory_turnover: {
    columns: [
      { title: '物料编码', key: 'material_code' },
      { title: '物料', key: 'material_name' },
      { title: '出库量', key: 'issue_qty' },
      { title: '入库量', key: 'receive_qty' },
      { title: '在库', key: 'on_hand' },
      { title: '安全库存', key: 'safety_stock' },
      { title: '周转次数', key: 'turnover_times' }
    ],
    chart: null
  },
  worker_performance: {
    columns: [
      { title: '工号', key: 'emp_no' },
      { title: '姓名', key: 'name' },
      { title: '岗位', key: 'position' },
      { title: '合格数', key: 'qty_good' },
      { title: '不良数', key: 'qty_defect' },
      { title: '工时(h)', key: 'labor_hour' },
      { title: '人均时产', key: 'per_hour_output' }
    ],
    chart: 'worker'
  }
}

const config = computed(() => VIEW_CONFIG[active.value] || { columns: [], chart: null })
const items = computed(() => payload.value?.items || [])

const chartOption = computed(() => {
  const rows = items.value
  const kind = config.value.chart
  if (!kind || !rows.length) return null

  if (kind === 'progress') {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 58, right: 20, top: 28, bottom: 60 },
      xAxis: { type: 'category', data: rows.map((r) => r.order_no), axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: 'value', name: '%' },
      series: [{ type: 'bar', data: rows.map((r) => r.progress), itemStyle: { color: '#2b579a' } }]
    }
  }
  if (kind === 'yield') {
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['良品率', '不良率'], textStyle: { fontSize: 12 } },
      grid: { left: 58, right: 20, top: 34, bottom: 40 },
      xAxis: { type: 'category', data: rows.map((r) => r.product_code) },
      yAxis: { type: 'value', max: 100, name: '%' },
      series: [
        { name: '良品率', type: 'bar', data: rows.map((r) => r.yield_rate), itemStyle: { color: '#189a5b' } },
        { name: '不良率', type: 'bar', data: rows.map((r) => r.defect_rate), itemStyle: { color: '#d3453c' } }
      ]
    }
  }
  if (kind === 'oee') {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 58, right: 20, top: 28, bottom: 46 },
      xAxis: { type: 'category', data: rows.map((r) => r.equipment_code) },
      yAxis: { type: 'value', max: 100, name: '%' },
      series: [{ type: 'bar', data: rows.map((r) => r.availability), itemStyle: { color: '#3f6fb5' } }]
    }
  }
  if (kind === 'output') {
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['合格数', '不良数'], textStyle: { fontSize: 12 } },
      grid: { left: 58, right: 20, top: 34, bottom: 40 },
      xAxis: { type: 'category', data: rows.map((r) => r.stat_date) },
      yAxis: { type: 'value' },
      series: [
        { name: '合格数', type: 'line', data: rows.map((r) => r.qty_good), itemStyle: { color: '#2b579a' } },
        { name: '不良数', type: 'line', data: rows.map((r) => r.qty_defect), itemStyle: { color: '#d3453c' } }
      ]
    }
  }
  if (kind === 'pareto') {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 58, right: 50, top: 28, bottom: 40 },
      xAxis: { type: 'category', data: rows.map((r) => r.defect_name) },
      yAxis: [
        { type: 'value', name: '数量' },
        { type: 'value', name: '累计%', max: 100 }
      ],
      series: [
        { name: '数量', type: 'bar', data: rows.map((r) => r.qty), itemStyle: { color: '#2b579a' } },
        { name: '累计占比', type: 'line', yAxisIndex: 1, data: rows.map((r) => r.cumulative_ratio), itemStyle: { color: '#d98b18' } }
      ]
    }
  }
  if (kind === 'worker') {
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 58, right: 20, top: 28, bottom: 40 },
      xAxis: { type: 'category', data: rows.map((r) => r.name) },
      yAxis: { type: 'value', name: '件/小时' },
      series: [{ type: 'bar', data: rows.map((r) => r.per_hour_output), itemStyle: { color: '#189a5b' } }]
    }
  }
  return null
})

async function query(code = active.value) {
  active.value = code
  error.value = ''
  try {
    payload.value = await reportApi.query(code, { days: days.value })
  } catch (e) {
    payload.value = null
    error.value = e.message
  }
}

onMounted(async () => {
  catalog.value = await reportApi.catalog()
  await query()
})
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>

    <div class="card">
      <div class="card-head">
        <h2>统计报表（8 张）</h2>
        <div class="toolbar" style="margin: 0">
          <select v-model.number="days" @change="query()">
            <option :value="7">近 7 天</option>
            <option :value="30">近 30 天</option>
            <option :value="90">近 90 天</option>
          </select>
        </div>
      </div>
      <div class="toolbar">
        <button
          v-for="item in catalog"
          :key="item.code"
          class="btn"
          :class="active === item.code ? '' : 'plain'"
          @click="query(item.code)"
        >
          {{ item.name }}
        </button>
      </div>
      <div class="small muted">
        当前：{{ catalog.find((c) => c.code === active)?.name }} ·
        {{ catalog.find((c) => c.code === active)?.module }}模块
      </div>
    </div>

    <div v-if="payload" class="card">
      <div class="card-head"><h2>汇总指标</h2></div>
      <div class="grid grid-4">
        <div v-for="(value, key) in payload.summary" :key="key">
          <div class="muted small">{{ key }}</div>
          <div style="font-size: 17px; font-weight: 600">{{ typeof value === 'number' ? num(value, 2) : value }}</div>
        </div>
      </div>
    </div>

    <div v-if="chartOption" class="card">
      <div class="card-head"><h2>图表视图</h2></div>
      <ChartBox :option="chartOption" height="300px" />
    </div>

    <div v-if="payload" class="card">
      <div class="card-head">
        <h2>明细数据（{{ items.length }} 行）</h2>
      </div>
      <DataTable :columns="config.columns" :rows="items">
        <template #cell-progress="{ value }">{{ pct(value, 1) }}</template>
        <template #cell-yield_rate="{ value }">{{ pct(value, 2) }}</template>
        <template #cell-defect_rate="{ value }">{{ pct(value, 2) }}</template>
        <template #cell-availability="{ value }">{{ pct(value, 2) }}</template>
        <template #cell-efficiency="{ value }">{{ pct(value, 1) }}</template>
        <template #cell-ratio="{ value }">{{ pct(value, 2) }}</template>
        <template #cell-cumulative_ratio="{ value }">{{ pct(value, 2) }}</template>
      </DataTable>
    </div>
  </div>
</template>
