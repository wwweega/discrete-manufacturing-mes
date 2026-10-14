<script setup>
/**
 * 车间看板（对应简历：「Redis 缓存设备实时状态，SSE 向前端推送，车间看板秒级刷新」）。
 *
 * 数据来源两条：
 *  - 业务面：REST 一次性拉取工单进度 / 今日产出 / 待办质检 / 库存预警；
 *  - 实时面：EventSource 订阅 /api/v1/dashboard/stream，由数采网关每 2 秒推送一帧。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ChartBox from '../components/ChartBox.vue'
import StatCard from '../components/StatCard.vue'
import DataTable from '../components/DataTable.vue'
import StatusTag from '../components/StatusTag.vue'
import { dashboardApi } from '../api/modules'
import { EQUIP_STATUS, ORDER_STATUS, dateText, pct } from '../utils/format'
import { getToken } from '../api/request'

const overview = ref(null)
const distribution = ref([])
const recent = ref([])
const trend = ref([])
const devices = ref([])
const alarms = ref([])
const error = ref('')
const live = ref(false)
const lastPush = ref('')

let source = null

const deviceColumns = [
  { title: '设备编码', key: 'equipment_code' },
  { title: '设备名称', key: 'equipment_name' },
  { title: '状态', key: 'status' },
  { title: '在制工单', key: 'work_order_no' },
  { title: '当前工序', key: 'operation_name' },
  { title: '负载率', key: 'load_rate' },
  { title: '温度', key: 'temperature' },
  { title: '累计产出', key: 'total_output' }
]

const recentColumns = [
  { title: '报工单号', key: 'report_no' },
  { title: '工单号', key: 'order_no' },
  { title: '合格数', key: 'qty_good' },
  { title: '不良数', key: 'qty_defect' },
  { title: '报工时间', key: 'report_time' }
]

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['合格数', '不良数'], textStyle: { fontSize: 12 } },
  grid: { left: 48, right: 18, top: 38, bottom: 32 },
  xAxis: { type: 'category', data: trend.value.map((i) => i.day) },
  yAxis: { type: 'value' },
  series: [
    { name: '合格数', type: 'bar', data: trend.value.map((i) => i.qty_good), itemStyle: { color: '#2b579a' } },
    { name: '不良数', type: 'bar', data: trend.value.map((i) => i.qty_defect), itemStyle: { color: '#d3453c' } }
  ]
}))

const pieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: { bottom: 0, textStyle: { fontSize: 12 } },
  series: [
    {
      type: 'pie',
      radius: ['42%', '66%'],
      data: distribution.value,
      label: { formatter: '{b} {c}' },
      color: ['#2b579a', '#189a5b', '#d98b18', '#d3453c', '#6b7787', '#3f6fb5']
    }
  ]
}))

async function loadStatic() {
  try {
    const [ov, dist, recentRows, trendRows, rt] = await Promise.all([
      dashboardApi.overview(),
      dashboardApi.distribution(),
      dashboardApi.recentReports(8),
      dashboardApi.outputTrend(10),
      dashboardApi.realtime()
    ])
    overview.value = ov
    distribution.value = dist
    recent.value = recentRows
    trend.value = trendRows.series || []
    devices.value = rt?.devices || []
  } catch (e) {
    error.value = e.message
  }
}

function connectStream() {
  if (!window.EventSource) return
  source = new EventSource(`/api/v1/dashboard/stream?token=${encodeURIComponent(getToken())}`)
  source.onopen = () => {
    live.value = true
  }
  source.addEventListener('dashboard', (evt) => {
    const frame = JSON.parse(evt.data)
    devices.value = frame.devices || []
    alarms.value = frame.alarms || []
    lastPush.value = frame.updated_at || ''
    live.value = true
  })
  source.onerror = () => {
    live.value = false
  }
}

onMounted(() => {
  loadStatic()
  connectStream()
})

onBeforeUnmount(() => source && source.close())
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>

    <div class="card">
      <div class="card-head">
        <h2>实时运行状态</h2>
        <div class="small muted">
          <span class="pulse" :class="{ off: !live }"></span>
          SSE {{ live ? '已连接（秒级刷新）' : '未连接' }}
          <span v-if="lastPush" style="margin-left: 8px">最近推送：{{ lastPush }}</span>
        </div>
      </div>
      <div class="grid grid-4">
        <StatCard label="在制设备" :value="devices.filter(d => d.status === 'RUN').length"
                  :unit="`/ ${devices.length} 台`" desc="数采网关实时上报" tone="success" />
        <StatCard label="设备稼动率"
                  :value="pct(devices.length ? (devices.filter(d => d.status === 'RUN').length / devices.length) * 100 : 0)"
                  desc="RUN 状态 / 总台数" />
        <StatCard label="今日合格数" :value="overview?.today?.qty_good ?? '-'" unit="件"
                  :desc="`今日良品率 ${pct(overview?.today?.yield_rate)}`" />
        <StatCard label="待处理质检" :value="overview?.quality?.pending_tasks ?? '-'" unit="单"
                  desc="含 SPC 自动告警生成" tone="warn" />
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>近 10 天产出趋势</h2></div>
        <ChartBox :option="trendOption" height="280px" />
      </div>
      <div class="card">
        <div class="card-head"><h2>工单状态分布</h2></div>
        <ChartBox :option="pieOption" height="280px" />
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        <h2>设备实时状态</h2>
        <button class="btn plain" @click="dashboardApi.collectOnce().then(loadStatic)">手动采集一帧</button>
      </div>
      <DataTable :columns="deviceColumns" :rows="devices" empty-text="暂无设备实时数据，点击「手动采集一帧」">
        <template #cell-status="{ value }"><StatusTag :map="EQUIP_STATUS" :value="value" /></template>
        <template #cell-load_rate="{ value }">{{ value }}%</template>
        <template #cell-temperature="{ value }">{{ value }} ℃</template>
        <template #cell-work_order_no="{ value }">{{ value || '—' }}</template>
        <template #cell-operation_name="{ value }">{{ value || '—' }}</template>
      </DataTable>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>最近报工流水</h2></div>
        <DataTable :columns="recentColumns" :rows="recent">
          <template #cell-report_time="{ value }">{{ dateText(value) }}</template>
        </DataTable>
      </div>
      <div class="card">
        <div class="card-head"><h2>告警与库存预警</h2></div>
        <div v-if="alarms.length" class="alert alert-error">
          <div v-for="(a, i) in alarms" :key="i">
            【{{ a.level }}】{{ a.equipment_code }} {{ a.message }}
          </div>
        </div>
        <div v-if="overview?.inventory?.low_stock_items?.length" class="alert alert-warn alert">
          <div>低于安全库存物料：</div>
          <div v-for="item in overview.inventory.low_stock_items" :key="item.material_code">
            {{ item.material_name }}（{{ item.material_code }}）现存 {{ item.on_hand }}，缺口 {{ item.gap }}
          </div>
        </div>
        <div v-if="!alarms.length && !overview?.inventory?.low_stock_count" class="empty">
          当前无告警，生产运行正常
        </div>
      </div>
    </div>
  </div>
</template>
