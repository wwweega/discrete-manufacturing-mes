<script setup>
/** 设备状态总览：实时快照 + 窗口内稼动率 + 告警台账。 */
import { computed, onMounted, ref } from 'vue'
import DataTable from '../components/DataTable.vue'
import StatusTag from '../components/StatusTag.vue'
import ChartBox from '../components/ChartBox.vue'
import { dashboardApi } from '../api/modules'
import { EQUIP_STATUS, dateText, pct } from '../utils/format'

const summary = ref(null)
const error = ref('')
const sinceHours = ref(24)

const columns = [
  { title: '设备编码', key: 'code' },
  { title: '设备名称', key: 'name' },
  { title: '型号', key: 'model' },
  { title: '台账状态', key: 'static_status' },
  { title: '实时状态', key: 'status' },
  { title: '负载率', key: 'load_rate' },
  { title: '温度', key: 'temperature' },
  { title: '累计产出', key: 'total_output' },
  { title: '在制工单', key: 'current_order' }
]

const alarmColumns = [
  { title: '告警单号', key: 'alarm_no' },
  { title: '设备', key: 'equipment_id' },
  { title: '类型', key: 'alarm_type' },
  { title: '级别', key: 'level' },
  { title: '描述', key: 'message' },
  { title: '发生时间', key: 'occurred_at' }
]

const utilization = computed(() => summary.value?.utilization || {})
const rows = computed(() => {
  const map = summary.value?.devices || []
  return map.map((d) => ({
    ...d,
    current_order: d.current_order || '—'
  }))
})

const barOption = computed(() => {
  const data = Object.entries(utilization.value).map(([id, v]) => ({
    id: Number(id),
    availability: v.availability,
    output: v.output
  }))
  const names = data.map((d) => `#${d.id}`)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['稼动率(%)', '产出(件)'], textStyle: { fontSize: 12 } },
    grid: { left: 48, right: 48, top: 38, bottom: 32 },
    xAxis: { type: 'category', data: names },
    yAxis: [
      { type: 'value', name: '稼动率%', max: 100 },
      { type: 'value', name: '产出' }
    ],
    series: [
      { name: '稼动率(%)', type: 'bar', data: data.map((d) => d.availability), itemStyle: { color: '#2b579a' } },
      { name: '产出(件)', type: 'line', yAxisIndex: 1, data: data.map((d) => d.output), itemStyle: { color: '#189a5b' } }
    ]
  }
})

async function load() {
  try {
    summary.value = await dashboardApi.equipmentSummary(sinceHours.value)
  } catch (e) {
    error.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>

    <div class="card">
      <div class="card-head">
        <h2>设备状态与稼动率</h2>
        <div>
          <select v-model.number="sinceHours" @change="load">
            <option :value="8">近 8 小时</option>
            <option :value="24">近 24 小时</option>
            <option :value="72">近 72 小时</option>
          </select>
          <button class="btn plain" style="margin-left: 6px" @click="dashboardApi.collectOnce().then(load)">
            手动采集一帧
          </button>
        </div>
      </div>

      <div class="grid grid-4" style="margin-bottom: 14px">
        <div class="card" style="margin-bottom: 0">
          <div class="muted small">设备总数</div>
          <div style="font-size: 22px; font-weight: 600">{{ summary?.equipment_count ?? '-' }}</div>
        </div>
        <div class="card" style="margin-bottom: 0">
          <div class="muted small">运行 / 待机 / 故障</div>
          <div style="font-size: 22px; font-weight: 600">
            {{ summary?.devices?.filter(d => d.status === 'RUN').length ?? 0 }} /
            {{ summary?.devices?.filter(d => d.status === 'IDLE').length ?? 0 }} /
            {{ summary?.devices?.filter(d => d.status === 'FAULT').length ?? 0 }}
          </div>
        </div>
        <div class="card" style="margin-bottom: 0">
          <div class="muted small">采集日志条数</div>
          <div style="font-size: 22px; font-weight: 600">{{ summary?.log_count ?? '-' }}</div>
        </div>
        <div class="card" style="margin-bottom: 0">
          <div class="muted small">未闭环告警</div>
          <div style="font-size: 22px; font-weight: 600">{{ summary?.alarm_summary?.total ?? 0 }}</div>
        </div>
      </div>

      <DataTable :columns="columns" :rows="rows" empty-text="暂无设备数据">
        <template #cell-static_status="{ value }"><StatusTag :map="EQUIP_STATUS" :value="value" /></template>
        <template #cell-status="{ value }"><StatusTag :map="EQUIP_STATUS" :value="value" /></template>
        <template #cell-load_rate="{ value }">{{ pct(value) }}</template>
        <template #cell-temperature="{ value }">{{ value }} ℃</template>
      </DataTable>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>各设备稼动率与产出</h2></div>
        <ChartBox :option="barOption" height="300px" />
      </div>
      <div class="card">
        <div class="card-head"><h2>告警台账</h2></div>
        <div class="muted small">
          数据来自数采网关运行日志：状态日志 {{ summary?.log_count ?? 0 }} 条，
          稼动率按窗口运行秒数 / 窗口时长计算。
        </div>
        <div class="grid grid-3" style="margin: 10px 0">
          <div v-for="level in ['CRITICAL', 'MAJOR', 'MINOR']" :key="level">
            <span class="tag" :class="level === 'CRITICAL' ? 'tag-danger' : level === 'MAJOR' ? 'tag-warn' : 'tag-muted'">
              {{ level }} {{ summary?.alarm_summary?.[level] ?? 0 }}
            </span>
          </div>
        </div>
        <div class="muted small">
          告警明细可在「设备状态」接口中查看；网关每次采集若触发异常会自动写入 eq_alarm。
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>采集时间轴</h2></div>
      <div class="small muted">
        最近一次采集时间：{{ summary?.devices?.[0]?.collected_at || '—' }}；
        网关上报周期可在后端配置 GATEWAY_INTERVAL_SEC 调整。
      </div>
    </div>
  </div>
</template>
