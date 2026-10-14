<script setup>
/**
 * SPC X̄-R 控制图（对应简历：「按 SPC 思路实现均值-极差控制图（X̄-R 图）计算与超限告警，
 * ECharts 可视化，异常批次自动生成待处理质检单」）。
 *
 * 控制限与判异全部由后端计算，前端只负责渲染——避免两套实现产生口径偏差。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import ChartBox from '../components/ChartBox.vue'
import { masterApi, qualityApi } from '../api/modules'
import { num, pct } from '../utils/format'

const master = ref(null)
const chart = ref(null)
const rules = ref({})
const error = ref('')
const message = ref('')

const query = reactive({ product_id: '', operation_code: '', tail: 30 })
const sampleForm = reactive({ values: '', feature_name: '' })

const spcOptions = computed(() => {
  const list = master.value?.routing_operations || []
  return list.filter((op) => op.spc_enabled)
})

const limits = computed(() => chart.value?.limits || {})

const xbarOption = computed(() => {
  if (!chart.value) return {}
  const c = chart.value
  const outSet = new Set(c.out_of_control_indexes || [])
  const points = c.means.map((v, i) => ({
    value: v,
    itemStyle: outSet.has(i) ? { color: '#d3453c' } : undefined
  }))
  const line = (y, label, color) => ({
    yAxis: y,
    label: { formatter: `${label} ${num(y, 4)}`, position: 'insideEndTop', fontSize: 11 },
    lineStyle: { color, type: 'dashed' }
  })
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 62, right: 22, top: 30, bottom: 34 },
    xAxis: { type: 'category', data: c.subgroup_nos, name: '子组号' },
    yAxis: { type: 'value', scale: true, name: '均值 X̄' },
    series: [
      {
        type: 'line',
        data: points,
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { color: '#2b579a' },
        itemStyle: { color: '#2b579a' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            line(limits.value.xbar_ucl, 'UCL', '#d3453c'),
            line(limits.value.xbar_center, 'CL', '#6b7787'),
            line(limits.value.xbar_lcl, 'LCL', '#d3453c'),
            ...(limits.value.upper_spec ? [line(limits.value.upper_spec, 'USL', '#d98b18')] : []),
            ...(limits.value.lower_spec ? [line(limits.value.lower_spec, 'LSL', '#d98b18')] : [])
          ]
        }
      }
    ]
  }
})

const rangeOption = computed(() => {
  if (!chart.value) return {}
  const c = chart.value
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 62, right: 22, top: 30, bottom: 34 },
    xAxis: { type: 'category', data: c.subgroup_nos, name: '子组号' },
    yAxis: { type: 'value', scale: true, name: '极差 R' },
    series: [
      {
        type: 'line',
        data: c.ranges,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: '#189a5b' },
        itemStyle: { color: '#189a5b' },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            { yAxis: limits.value.r_ucl, label: { formatter: `UCL ${num(limits.value.r_ucl, 4)}`, fontSize: 11 }, lineStyle: { color: '#d3453c', type: 'dashed' } },
            { yAxis: limits.value.r_center, label: { formatter: `CL ${num(limits.value.r_center, 4)}`, fontSize: 11 }, lineStyle: { color: '#6b7787', type: 'dashed' } },
            { yAxis: limits.value.r_lcl, label: { formatter: `LCL ${num(limits.value.r_lcl, 4)}`, fontSize: 11 }, lineStyle: { color: '#d3453c', type: 'dashed' } }
          ]
        }
      }
    ]
  }
})

async function loadChart() {
  if (!query.product_id || !query.operation_code) return
  error.value = ''
  try {
    chart.value = await qualityApi.chart(query.product_id, query.operation_code, query.tail)
  } catch (e) {
    chart.value = null
    error.value = e.message
  }
}

async function submitSample() {
  message.value = ''
  try {
    const values = sampleForm.values.split(',').map((v) => Number(v.trim())).filter((v) => !Number.isNaN(v))
    const src = spcOptions.value.find((o) => o.operation_code === query.operation_code)
    const result = await qualityApi.addSubgroup({
      product_id: Number(query.product_id),
      operation_code: query.operation_code,
      values,
      feature_name: sampleForm.feature_name || src?.spc_feature_name || '关键尺寸',
      nominal: src?.spc_nominal ?? 0,
      upper_spec: src?.spc_upper ?? 0,
      lower_spec: src?.spc_lower ?? 0
    })
    message.value = result.is_out_of_control
      ? `子组 #${result.subgroup_no} 触发判异（${result.alarm_rules}），已自动生成质检单 ${result.inspection_task_no}`
      : `子组 #${result.subgroup_no} 已录入，均值 ${result.mean_value}，未触发判异`
    await loadChart()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  master.value = await masterApi.all()
  rules.value = await qualityApi.rules().then((r) => r.rules)
  const first = spcOptions.value[0]
  if (first) {
    query.product_id = master.value.routings.find((r) => r.id === first.routing_id)?.product_id
    query.operation_code = first.operation_code
    await loadChart()
  }
})
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert" :class="message.includes('判异（') ? 'alert-error' : 'alert-success'">
      {{ message }}
    </div>

    <div class="card">
      <div class="card-head">
        <h2>SPC 均值-极差（X̄-R）控制图</h2>
        <div class="toolbar" style="margin: 0">
          <select v-model="query.product_id" @change="loadChart">
            <option value="">选择产品</option>
            <option v-for="p in master?.products || []" :key="p.id" :value="p.id">{{ p.code }} {{ p.name }}</option>
          </select>
          <select v-model="query.operation_code" @change="loadChart">
            <option value="">选择受控工序</option>
            <option v-for="op in spcOptions" :key="op.id" :value="op.operation_code">
              {{ op.operation_code }} {{ op.operation_name }}（{{ op.spc_feature_name }}）
            </option>
          </select>
          <select v-model.number="query.tail" @change="loadChart">
            <option :value="20">近 20 组</option>
            <option :value="30">近 30 组</option>
            <option :value="50">近 50 组</option>
          </select>
        </div>
      </div>

      <div v-if="chart" class="grid grid-4">
        <div><div class="muted small">子组容量 n</div><div>{{ limits.subgroup_size }}（共 {{ limits.subgroups }} 组）</div></div>
        <div><div class="muted small">中心线 X̄̄ / R̄</div><div>{{ num(limits.xbar_center, 4) }} / {{ num(limits.r_center, 4) }}</div></div>
        <div><div class="muted small">X̄ 图控制限</div><div>{{ num(limits.xbar_lcl, 4) }} ~ {{ num(limits.xbar_ucl, 4) }}</div></div>
        <div><div class="muted small">过程能力</div><div>Cp {{ limits.cp }} / Cpk {{ limits.cpk }}</div></div>
      </div>
      <div v-if="chart && !limits.is_established" class="alert alert-info" style="margin-top: 10px">
        {{ limits.message }}
      </div>
    </div>

    <div v-if="chart" class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>X̄ 图（均值）</h2></div>
        <ChartBox :option="xbarOption" height="300px" />
      </div>
      <div class="card">
        <div class="card-head"><h2>R 图（极差）</h2></div>
        <ChartBox :option="rangeOption" height="300px" />
      </div>
    </div>

    <div v-if="chart" class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>判异命中记录</h2></div>
        <table v-if="chart.violations?.length">
          <thead><tr><th>子组</th><th>准则</th><th>说明</th><th>数值</th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in chart.violations" :key="i">
              <td>#{{ v.subgroup_no }}</td>
              <td><span class="tag tag-danger">{{ v.rule }}</span></td>
              <td>{{ v.description }}</td>
              <td>{{ v.value }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">当前窗口内未命中判异准则，过程受控</div>
      </div>

      <div class="card">
        <div class="card-head"><h2>录入新子组</h2></div>
        <div class="toolbar">
          <input v-model="sampleForm.values" style="width: 260px" placeholder="样本值，逗号分隔，如 40.01,39.99,40.02" />
          <input v-model="sampleForm.feature_name" style="width: 120px" placeholder="特性名称" />
          <button class="btn" @click="submitSample">提交采样</button>
        </div>
        <div class="small muted">判异准则（GB/T 4091 全 8 条，默认启用 1/2/3/5/6）：</div>
        <ul class="small muted" style="padding-left: 18px; margin-top: 6px">
          <li v-for="(desc, code) in rules" :key="code">{{ code }}：{{ desc }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>
