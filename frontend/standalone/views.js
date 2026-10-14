/**
 * 免构建演示版视图组件。
 *
 * 说明：与 Vite 工程版（frontend/src）功能同源、调用同一套 REST API，
 * 但这里不使用单文件组件（.vue），而是 Vue3 的「模板字符串 + Options API」写法，
 * 因此**无需 npm install / 构建**即可直接由 FastAPI 静态托管运行。
 */
import {
  api, fmt, getToken,
  ORDER_STATUS, OP_STATUS, EQUIP_STATUS, QC_STATUS
} from './api.js'

const { num, pct, date } = fmt

/** 极简表格渲染器：columns 为 {title, key, fmt} 数组 */
const SimpleTable = {
  props: { columns: Array, rows: Array, empty: { type: String, default: '暂无数据' } },
  template: `
    <div>
      <table v-if="rows && rows.length">
        <thead>
          <tr><th v-for="c in columns" :key="c.key">{{ c.title }}</th></th></tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in rows" :key="i">
            <td v-for="c in columns" :key="c.key">
              {{ c.fmt ? c.fmt(row[c.key], row) : (row[c.key] ?? '-') }}
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">{{ empty }}</div>
    </div>
  `
}

const Tag = {
  props: { map: Object, value: String },
  template: `<span class="tag" :class="'tag-' + ((map && map[value] && map[value].tone) || 'muted')">
    {{ (map && map[value] && map[value].label) || value || '-' }}</span>`
}

/** ECharts 容器：接收 option 字符串化后的对象，自动初始化与销毁 */
const Chart = {
  props: { option: Object, height: { type: String, default: '300px' } },
  template: `<div ref="el" class="chart" :style="{ height }"></div>`,
  mounted() {
    this.chart = window.echarts.init(this.$refs.el)
    this.chart.setOption(this.option, true)
    this._onResize = () => this.chart && this.chart.resize()
    window.addEventListener('resize', this._onResize)
  },
  watch: {
    option(val) {
      if (this.chart) this.chart.setOption(val, true)
    }
  },
  beforeUnmount() {
    window.removeEventListener('resize', this._onResize)
    if (this.chart) this.chart.dispose()
  }
}

/* ------------------------------------------------------------------ 看板 */
export const DashboardView = {
  components: { SimpleTable, Tag, Chart },
  data() {
    return {
      overview: null,
      devices: [],
      alarms: [],
      recent: [],
      distribution: [],
      live: false,
      lastPush: '',
      error: ''
    }
  },
  computed: {
    EQUIP_STATUS: () => EQUIP_STATUS,
    pieOption() {
      return {
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { bottom: 0 },
        series: [{
          type: 'pie',
          radius: ['42%', '66%'],
          data: this.distribution,
          color: ['#2b579a', '#189a5b', '#d98b18', '#d3453c', '#6b7787', '#3f6fb5']
        }]
      }
    }
  },
  methods: {
    pct,
    async load() {
      try {
        this.overview = await api.overview()
        this.distribution = await api.distribution()
        this.recent = await api.recentReports(8)
        const rt = await api.realtime()
        this.devices = (rt && rt.devices) || []
      } catch (e) {
        this.error = e.message
      }
    },
    connect() {
      if (!window.EventSource) return
      const es = new EventSource(`/api/v1/dashboard/stream?token=${encodeURIComponent(getToken())}`)
      es.onopen = () => { this.live = true }
      es.addEventListener('dashboard', (evt) => {
        const frame = JSON.parse(evt.data)
        this.devices = frame.devices || []
        this.alarms = frame.alarms || []
        this.lastPush = frame.updated_at || ''
        this.live = true
      })
      es.onerror = () => { this.live = false }
      this._es = es
    },
    async collect() {
      await api.collectOnce()
      await this.load()
    }
  },
  mounted() {
    this.load()
    this.connect()
  },
  beforeUnmount() { if (this._es) this._es.close() },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div class="card">
      <div class="card-head">
        <h2>实时运行状态</h2>
        <div class="small muted">
          <span class="pulse" :class="{ off: !live }"></span>
          SSE {{ live ? '已连接（秒级刷新）' : '未连接' }}
          <span v-if="lastPush"> · 最近推送 {{ lastPush }}</span>
        </div>
      </div>
      <div class="grid grid-4">
        <div class="card" style="margin-bottom:0">
          <div class="muted small">在制设备</div>
          <div style="font-size:22px;font-weight:600">{{ devices.filter(d => d.status === 'RUN').length }} / {{ devices.length }}</div>
        </div>
        <div class="card" style="margin-bottom:0">
          <div class="muted small">今日合格数</div>
          <div style="font-size:22px;font-weight:600">{{ overview && overview.today ? overview.today.qty_good : '-' }}</div>
        </div>
        <div class="card" style="margin-bottom:0">
          <div class="muted small">今日良品率</div>
          <div style="font-size:22px;font-weight:600">{{ overview && overview.today ? pct(overview.today.yield_rate) : '-' }}</div>
        </div>
        <div class="card" style="margin-bottom:0">
          <div class="muted small">待处理质检</div>
          <div style="font-size:22px;font-weight:600">{{ overview && overview.quality ? overview.quality.pending_tasks : '-' }}</div>
        </div>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>工单状态分布</h2></div>
        <Chart :option="pieOption" height="280px" />
      </div>
      <div class="card">
        <div class="card-head">
          <h2>设备实时状态</h2>
          <button class="btn plain" @click="collect">手动采集一帧</button>
        </div>
        <SimpleTable :columns="[
          { title: '设备', key: 'equipment_code' },
          { title: '状态', key: 'status' },
          { title: '在制工单', key: 'work_order_no' },
          { title: '负载率', key: 'load_rate' },
          { title: '温度', key: 'temperature' }
        ]" :rows="devices" />
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>最近报工流水</h2></div>
      <SimpleTable :columns="[
        { title: '报工单号', key: 'report_no' },
        { title: '工单号', key: 'order_no' },
        { title: '合格数', key: 'qty_good' },
        { title: '不良数', key: 'qty_defect' },
        { title: '报工时间', key: 'report_time', fmt: (v) => date(v) }
      ]" :rows="recent" />
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 工单 */
export const OrdersView = {
  components: { SimpleTable, Tag },
  data() {
    return {
      rows: [], detail: null, master: null, error: '', message: '',
      filter: { status: '' },
      form: { product_id: '', routing_id: '', qty_planned: 200, priority: 5 },
      showCreate: false,
      labels: { RELEASED: '下达', IN_PROGRESS: '开工', PAUSED: '暂停', COMPLETED: '完工', CANCELLED: '作废' }
    }
  },
  computed: { ORDER_STATUS: () => ORDER_STATUS, OP_STATUS: () => OP_STATUS },
  methods: {
    pct,
    async load() {
      try {
        const data = await api.orders({ status: this.filter.status || undefined })
        this.rows = data.items
      } catch (e) { this.error = e.message }
    },
    async open(id) { this.detail = await api.orderDetail(id) },
    async move(status) {
      try {
        await api.transition(this.detail.order.id, { target_status: status, reason: '前端操作' })
        this.message = `工单已流转至 ${status}`
        this.detail = await api.orderDetail(this.detail.order.id)
        await this.load()
      } catch (e) { this.error = e.message }
    },
    async create() {
      try {
        await api.createOrder({
          product_id: Number(this.form.product_id),
          routing_id: Number(this.form.routing_id),
          qty_planned: Number(this.form.qty_planned),
          priority: Number(this.form.priority)
        })
        this.showCreate = false
        this.message = '工单创建成功（草稿状态）'
        await this.load()
      } catch (e) { this.error = e.message }
    }
  },
  async mounted() {
    this.master = await api.master()
    await this.load()
  },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>
    <div class="card">
      <div class="card-head">
        <h2>生产工单</h2>
        <button class="btn" @click="showCreate = !showCreate">{{ showCreate ? '收起' : '新建工单' }}</button>
      </div>
      <div v-if="showCreate" class="toolbar">
        <select v-model="form.product_id">
          <option value="">选择产品</option>
          <option v-for="p in (master && master.products) || []" :key="p.id" :value="p.id">{{ p.code }} {{ p.name }}</option>
        </select>
        <select v-model="form.routing_id">
          <option value="">选择工艺路线</option>
          <option v-for="r in (master && master.routings) || []" :key="r.id" :value="r.id">{{ r.routing_code }}</option>
        </select>
        <input v-model="form.qty_planned" type="number" style="width:110px" placeholder="计划产量" />
        <button class="btn" @click="create">提交</button>
      </div>
      <div class="toolbar">
        <select v-model="filter.status" @change="load">
          <option value="">全部状态</option>
          <option v-for="(v, k) in ORDER_STATUS" :key="k" :value="k">{{ v.label }}</option>
        </select>
      </div>
      <table>
        <thead><tr><th>工单号</th><th>产品</th><th>状态</th><th>计划</th><th>完成</th><th>进度</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.order_no }}</td>
            <td>{{ r.product_name || r.product_id }}</td>
            <td><Tag :map="ORDER_STATUS" :value="r.status" /></td>
            <td>{{ r.qty_planned }}</td>
            <td>{{ r.qty_completed }}</td>
            <td>{{ pct(r.progress, 1) }}</td>
            <td><a href="javascript:void(0)" @click="open(r.id)">详情</a></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="detail" class="card">
      <div class="card-head">
        <h2>工单详情 · {{ detail.order.order_no }}</h2>
        <div>
          <Tag :map="ORDER_STATUS" :value="detail.order.status" />
          <button v-for="t in detail.allowed_transitions" :key="t" class="btn" style="margin-left:6px" @click="move(t)">
            {{ labels[t] || t }}
          </button>
        </div>
      </div>
      <table>
        <thead><tr><th>序号</th><th>工序</th><th>状态</th><th>计划</th><th>完成</th><th>合格</th><th>不良</th></tr></thead>
        <tbody>
          <tr v-for="op in detail.operations" :key="op.id">
            <td>{{ op.seq }}</td>
            <td>{{ op.operation_code }} {{ op.operation_name }}</td>
            <td><Tag :map="OP_STATUS" :value="op.status" /></td>
            <td>{{ op.plan_qty }}</td><td>{{ op.done_qty }}</td>
            <td>{{ op.good_qty }}</td><td>{{ op.defect_qty }}</td>
          </tr>
        </tbody>
      </table>
      <div style="margin-top:12px" class="small muted">
        物料需求：
        <span v-for="m in detail.materials" :key="m.id" style="margin-right:12px">
          {{ m.material_name || '#' + m.material_id }}（需 {{ m.qty_required }} / 已发 {{ m.qty_issued }}）
        </span>
      </div>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 报工 */
export const ReportWorkView = {
  components: { Tag },
  data() {
    return {
      orders: [], master: null, detail: null, result: null,
      form: { operation_id: '', qty_good: 50, qty_defect: 0, employee_id: '', measurements: '' },
      lastKey: '', message: '', error: '', submitting: false
    }
  },
  computed: { ORDER_STATUS: () => ORDER_STATUS },
  methods: {
    pct,
    newKey: () => `ui-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
    async load() {
      this.master = await api.master()
      const list = await api.orders({ status: 'IN_PROGRESS' })
      this.orders = list.items
      if (this.orders.length) await this.select(this.orders[0].id)
    },
    async select(id) { this.detail = await api.orderDetail(id); this.result = null },
    async submit(reuse) {
      this.error = ''; this.message = ''; this.submitting = true
      try {
        const key = reuse ? this.lastKey : this.newKey()
        this.lastKey = key
        const measurements = this.form.measurements
          ? this.form.measurements.split(',').map((v) => Number(v.trim())).filter((v) => !Number.isNaN(v))
          : []
        this.result = await api.report(this.detail.order.id, {
          operation_id: Number(this.form.operation_id),
          qty_good: Number(this.form.qty_good),
          qty_defect: Number(this.form.qty_defect || 0),
          employee_id: this.form.employee_id ? Number(this.form.employee_id) : null,
          measurements
        }, key)
        this.message = this.result.duplicated
          ? `重复提交被幂等拦截，返回首次报工单号 ${this.result.report_no}`
          : `报工成功：${this.result.report_no}`
        this.detail = await api.orderDetail(this.detail.order.id)
      } catch (e) {
        this.error = e.message
      } finally { this.submitting = false }
    }
  },
  mounted() { this.load() },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert" :class="result && result.duplicated ? 'alert-info' : 'alert-success'">{{ message }}</div>
    <div class="card">
      <div class="card-head">
        <h2>工序报工（幂等演示）</h2>
        <select @change="(e) => select(Number(e.target.value))">
          <option v-for="o in orders" :key="o.id" :value="o.id">{{ o.order_no }}</option>
        </select>
      </div>
      <div class="toolbar">
        <select v-model="form.operation_id">
          <option value="">选择工序</option>
          <option v-for="op in (detail && detail.operations) || []" :key="op.id" :value="op.id">
            {{ op.operation_code }} {{ op.operation_name }}（剩余 {{ op.plan_qty - op.done_qty }}）
          </option>
        </select>
        <input v-model="form.qty_good" type="number" style="width:100px" placeholder="合格数" />
        <input v-model="form.qty_defect" type="number" style="width:100px" placeholder="不良数" />
        <select v-model="form.employee_id">
          <option value="">选择操作员</option>
          <option v-for="e in (master && master.employees) || []" :key="e.id" :value="e.id">{{ e.emp_no }} {{ e.name }}</option>
        </select>
        <input v-model="form.measurements" style="width:210px" placeholder="SPC样本，逗号分隔（可空）" />
        <button class="btn" :disabled="!form.operation_id || submitting" @click="submit(false)">提交报工</button>
        <button class="btn ghost" :disabled="!lastKey" @click="submit(true)">用同一幂等键重复提交</button>
      </div>
      <div class="small muted">当前幂等键：<code>{{ lastKey || '提交后生成' }}</code></div>
    </div>

    <div v-if="result" class="card">
      <div class="card-head"><h2>报工结果</h2></div>
      <div class="grid grid-4">
        <div><div class="muted small">报工单号</div><div>{{ result.report_no }}</div></div>
        <div><div class="muted small">工序完成量</div><div>{{ result.operation_done_qty }}</div></div>
        <div><div class="muted small">工单进度</div><div>{{ pct(result.order_progress, 1) }}</div></div>
        <div><div class="muted small">自动完工</div><div>{{ result.auto_completed ? '是' : '否' }}</div></div>
      </div>
      <div v-if="result.inventory_flows && result.inventory_flows.length" style="margin-top:12px">
        <div class="muted small">库存扣减流水（库存联动）：</div>
        <table>
          <thead><tr><th>流水号</th><th>物料ID</th><th>扣减量</th><th>扣后结存</th></tr></thead>
          <tbody>
            <tr v-for="f in result.inventory_flows" :key="f.tx_no">
              <td>{{ f.tx_no }}</td><td>{{ f.material_id }}</td><td>{{ f.qty }}</td><td>{{ f.balance_after }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="result.spc" class="alert alert-info" style="margin-top:10px">
        SPC 子组 #{{ result.spc.subgroup_no }} 均值 {{ result.spc.mean_value }}，
        {{ result.spc.is_out_of_control ? '触发判异（' + result.spc.alarm_rules + '），已生成 ' + result.spc.inspection_task_no : '未触发判异' }}
      </div>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 设备 */
export const EquipmentView = {
  components: { SimpleTable, Tag },
  data() { return { summary: null, error: '' } },
  computed: { EQUIP_STATUS: () => EQUIP_STATUS },
  methods: {
    pct,
    async load() {
      try { this.summary = await api.equipmentSummary(24) } catch (e) { this.error = e.message }
    },
    async collect() { await api.collectOnce(); await this.load() }
  },
  mounted() { this.load() },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div class="card">
      <div class="card-head">
        <h2>设备状态与稼动率（近 24 小时）</h2>
        <button class="btn plain" @click="collect">手动采集一帧</button>
      </div>
      <div class="grid grid-4" style="margin-bottom:12px">
        <div class="card" style="margin-bottom:0"><div class="muted small">设备总数</div><div style="font-size:22px;font-weight:600">{{ summary ? summary.equipment_count : '-' }}</div></div>
        <div class="card" style="margin-bottom:0"><div class="muted small">运行台数</div><div style="font-size:22px;font-weight:600">{{ summary ? summary.devices.filter(d => d.status === 'RUN').length : '-' }}</div></div>
        <div class="card" style="margin-bottom:0"><div class="muted small">采集日志</div><div style="font-size:22px;font-weight:600">{{ summary ? summary.log_count : '-' }}</div></div>
        <div class="card" style="margin-bottom:0"><div class="muted small">未闭环告警</div><div style="font-size:22px;font-weight:600">{{ summary ? summary.alarm_summary.total : '-' }}</div></div>
      </div>
      <table>
        <thead><tr><th>设备</th><th>名称</th><th>实时状态</th><th>负载率</th><th>温度</th><th>累计产出</th><th>在制工单</th></tr></thead>
        <tbody>
          <tr v-for="d in (summary && summary.devices) || []" :key="d.id">
            <td>{{ d.code }}</td>
            <td>{{ d.name }}</td>
            <td><Tag :map="EQUIP_STATUS" :value="d.status" /></td>
            <td>{{ pct(d.load_rate) }}</td>
            <td>{{ d.temperature }} ℃</td>
            <td>{{ d.total_output }}</td>
            <td>{{ d.current_order || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ SPC */
export const SpcView = {
  components: { Chart },
  data() {
    return {
      master: null, chart: null, rules: {}, error: '', message: '',
      query: { product_id: '', operation_code: '', tail: 30 },
      sample: { values: '', feature_name: '' }
    }
  },
  computed: {
    spcOps() {
      return ((this.master && this.master.routing_operations) || []).filter((o) => o.spc_enabled)
    },
    xbarOption() {
      if (!this.chart) return {}
      const c = this.chart
      const out = new Set(c.out_of_control_indexes || [])
      const mk = (y, label, color) => ({
        yAxis: y, label: { formatter: `${label} ${num(y, 4)}`, fontSize: 11 },
        lineStyle: { color, type: 'dashed' }
      })
      return {
        tooltip: { trigger: 'axis' },
        grid: { left: 62, right: 22, top: 28, bottom: 34 },
        xAxis: { type: 'category', data: c.subgroup_nos },
        yAxis: { type: 'value', scale: true, name: 'X̄' },
        series: [{
          type: 'line', symbol: 'circle', symbolSize: 7,
          data: c.means.map((v, i) => ({ value: v, itemStyle: out.has(i) ? { color: '#d3453c' } : {} })),
          lineStyle: { color: '#2b579a' }, itemStyle: { color: '#2b579a' },
          markLine: { silent: true, symbol: 'none', data: [
            mk(c.limits.xbar_ucl, 'UCL', '#d3453c'),
            mk(c.limits.xbar_center, 'CL', '#6b7787'),
            mk(c.limits.xbar_lcl, 'LCL', '#d3453c')
          ] }
        }]
      }
    },
    rangeOption() {
      if (!this.chart) return {}
      const c = this.chart
      return {
        tooltip: { trigger: 'axis' },
        grid: { left: 62, right: 22, top: 28, bottom: 34 },
        xAxis: { type: 'category', data: c.subgroup_nos },
        yAxis: { type: 'value', scale: true, name: 'R' },
        series: [{
          type: 'line', symbol: 'circle', symbolSize: 6, data: c.ranges,
          lineStyle: { color: '#189a5b' }, itemStyle: { color: '#189a5b' },
          markLine: { silent: true, symbol: 'none', data: [
            { yAxis: c.limits.r_ucl, label: { formatter: 'UCL ' + num(c.limits.r_ucl, 4), fontSize: 11 }, lineStyle: { color: '#d3453c', type: 'dashed' } },
            { yAxis: c.limits.r_center, label: { formatter: 'CL ' + num(c.limits.r_center, 4), fontSize: 11 }, lineStyle: { color: '#6b7787', type: 'dashed' } }
          ] }
        }]
      }
    }
  },
  methods: {
    num,
    async loadChart() {
      if (!this.query.product_id || !this.query.operation_code) return
      try { this.chart = await api.spcChart(this.query.product_id, this.query.operation_code, this.query.tail) }
      catch (e) { this.chart = null; this.error = e.message }
    },
    async submitSample() {
      this.message = ''
      try {
        const values = this.sample.values.split(',').map((v) => Number(v.trim())).filter((v) => !Number.isNaN(v))
        const src = this.spcOps.find((o) => o.operation_code === this.query.operation_code)
        const r = await api.addSubgroup({
          product_id: Number(this.query.product_id),
          operation_code: this.query.operation_code,
          values,
          feature_name: this.sample.feature_name || (src && src.spc_feature_name) || '关键尺寸',
          nominal: src ? src.spc_nominal : 0,
          upper_spec: src ? src.spc_upper : 0,
          lower_spec: src ? src.spc_lower : 0
        })
        this.message = r.is_out_of_control
          ? `子组 #${r.subgroup_no} 触发判异（${r.alarm_rules}），已自动生成质检单 ${r.inspection_task_no}`
          : `子组 #${r.subgroup_no} 已录入，均值 ${r.mean_value}，未触发判异`
        await this.loadChart()
      } catch (e) { this.error = e.message }
    }
  },
  async mounted() {
    try {
      this.master = await api.master()
      this.rules = (await api.spcRules()).rules
      const first = this.spcOps[0]
      if (first) {
        const routing = this.master.routings.find((r) => r.id === first.routing_id)
        this.query.product_id = routing ? routing.product_id : ''
        this.query.operation_code = first.operation_code
        await this.loadChart()
      }
    } catch (e) { this.error = e.message }
  },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert" :class="message.indexOf('判异（') >= 0 ? 'alert-error' : 'alert-success'">{{ message }}</div>
    <div class="card">
      <div class="card-head">
        <h2>SPC X̄-R 控制图</h2>
        <div class="toolbar" style="margin:0">
          <select v-model="query.operation_code" @change="loadChart">
            <option value="">选择受控工序</option>
            <option v-for="op in spcOps" :key="op.id" :value="op.operation_code">
              {{ op.operation_code }} {{ op.operation_name }}（{{ op.spc_feature_name }}）
            </option>
          </select>
          <select v-model.number="query.tail" @change="loadChart">
            <option :value="20">近 20 组</option><option :value="30">近 30 组</option><option :value="50">近 50 组</option>
          </select>
        </div>
      </div>
      <div v-if="chart" class="grid grid-4">
        <div><div class="muted small">子组 n / 组数</div><div>{{ chart.limits.subgroup_size }} / {{ chart.limits.subgroups }}</div></div>
        <div><div class="muted small">X̄̄ / R̄</div><div>{{ num(chart.limits.xbar_center, 4) }} / {{ num(chart.limits.r_center, 4) }}</div></div>
        <div><div class="muted small">X̄ 控制限</div><div>{{ num(chart.limits.xbar_lcl, 4) }} ~ {{ num(chart.limits.xbar_ucl, 4) }}</div></div>
        <div><div class="muted small">Cp / Cpk</div><div>{{ chart.limits.cp }} / {{ chart.limits.cpk }}</div></div>
      </div>
    </div>

    <div v-if="chart" class="grid grid-2">
      <div class="card"><div class="card-head"><h2>X̄ 图</h2></div><Chart :option="xbarOption" height="290px" /></div>
      <div class="card"><div class="card-head"><h2>R 图</h2></div><Chart :option="rangeOption" height="290px" /></div>
    </div>

    <div v-if="chart" class="grid grid-2">
      <div class="card">
        <div class="card-head"><h2>判异命中</h2></div>
        <table v-if="chart.violations.length">
          <thead><tr><th>子组</th><th>准则</th><th>说明</th><th>数值</th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in chart.violations" :key="i">
              <td>#{{ v.subgroup_no }}</td>
              <td><span class="tag tag-danger">{{ v.rule }}</span></td>
              <td>{{ v.description }}</td><td>{{ v.value }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">窗口内未命中判异准则，过程受控</div>
      </div>
      <div class="card">
        <div class="card-head"><h2>录入新子组</h2></div>
        <div class="toolbar">
          <input v-model="sample.values" style="width:250px" placeholder="样本值，逗号分隔" />
          <button class="btn" @click="submitSample">提交采样</button>
        </div>
        <ul class="small muted" style="padding-left:18px">
          <li v-for="(d, c) in rules" :key="c">{{ c }}：{{ d }}</li>
        </ul>
      </div>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 质检 */
export const QualityView = {
  components: { Tag },
  data() { return { rows: [], pending: 0, error: '', message: '', filter: { status: '' } } },
  computed: { QC_STATUS: () => QC_STATUS },
  methods: {
    async load() {
      try {
        const data = await api.tasks({ status: this.filter.status || undefined })
        this.rows = data.items
        this.pending = data.pending_count
      } catch (e) { this.error = e.message }
    },
    async move(t, status) {
      try {
        await api.taskMove(t.id, { target_status: status })
        this.message = `${t.task_no} 已流转至 ${status}`
        await this.load()
      } catch (e) { this.error = e.message }
    }
  },
  mounted() { this.load() },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>
    <div class="card">
      <div class="card-head">
        <h2>质检单（待处理 {{ pending }} 单）</h2>
        <select v-model="filter.status" @change="load">
          <option value="">全部状态</option>
          <option v-for="(v, k) in QC_STATUS" :key="k" :value="k">{{ v.label }}</option>
        </select>
      </div>
      <table>
        <thead><tr><th>质检单号</th><th>工单</th><th>来源</th><th>状态</th><th>抽检</th><th>不良</th><th>生成原因</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="t in rows" :key="t.id">
            <td>{{ t.task_no }}</td>
            <td>{{ t.order_no || '—' }}</td>
            <td><span class="tag" :class="t.source === 'SPC_ALERT' ? 'tag-danger' : 'tag-muted'">{{ t.source }}</span></td>
            <td><Tag :map="QC_STATUS" :value="t.status" /></td>
            <td>{{ t.sample_qty }}</td><td>{{ t.defect_qty }}</td>
            <td :title="t.trigger_reason">{{ (t.trigger_reason || '—').slice(0, 30) }}</td>
            <td>
              <a v-if="t.status === 'PENDING'" href="javascript:void(0)" @click="move(t, 'TESTING')">开始检验</a>
              <span v-if="t.status === 'TESTING'">
                <a href="javascript:void(0)" @click="move(t, 'PASSED')">合格</a>
                <a href="javascript:void(0)" style="margin-left:6px" @click="move(t, 'FAILED')">不合格</a>
              </span>
              <a v-if="t.status === 'PASSED' || t.status === 'FAILED'" href="javascript:void(0)" @click="move(t, 'CLOSED')">关闭</a>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 库存 */
export const InventoryView = {
  data() {
    return { stock: [], flows: [], materials: [], warehouses: [], error: '', message: '',
      form: { material_id: '', warehouse_id: '', qty: 10 } }
  },
  methods: {
    num,
    async load() {
      try {
        const data = await api.stock({})
        this.stock = data.items
        this.flows = await api.flows({ limit: 50 })
      } catch (e) { this.error = e.message }
    },
    async issue() {
      try {
        await api.issue({
          material_id: Number(this.form.material_id),
          warehouse_id: Number(this.form.warehouse_id),
          qty: Number(this.form.qty)
        })
        this.message = '发料成功，已生成出库流水'
        await this.load()
      } catch (e) { this.error = e.message }
    }
  },
  async mounted() {
    const master = await api.master()
    this.materials = master.materials
    this.warehouses = master.warehouses
    await this.load()
  },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>
    <div class="card">
      <div class="card-head"><h2>库存余额</h2></div>
      <table>
        <thead><tr><th>物料</th><th>仓库</th><th>在库</th><th>可用</th><th>安全库存</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="s in stock" :key="s.material_id + '-' + s.warehouse_id">
            <td>{{ s.material_code }} {{ s.material_name }}</td>
            <td>{{ s.warehouse_name }}</td>
            <td>{{ num(s.qty_on_hand, 2) }}</td>
            <td>{{ num(s.qty_available, 2) }}</td>
            <td>{{ num(s.safety_stock, 2) }}</td>
            <td><span class="tag" :class="s.below_safety ? 'tag-danger' : 'tag-success'">{{ s.below_safety ? '低于安全库存' : '正常' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-head"><h2>工单发料</h2></div>
      <div class="toolbar">
        <select v-model="form.material_id">
          <option value="">选择物料</option>
          <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.code }} {{ m.name }}</option>
        </select>
        <select v-model="form.warehouse_id">
          <option value="">选择仓库</option>
          <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.name }}</option>
        </select>
        <input v-model="form.qty" type="number" style="width:110px" placeholder="发料数量" />
        <button class="btn" @click="issue">发料</button>
      </div>
      <div class="small muted">库存不足时后端返回 409 并回滚，不会出现负库存。</div>
    </div>
    <div class="card">
      <div class="card-head"><h2>库存流水（最近 50 条）</h2></div>
      <table>
        <thead><tr><th>流水号</th><th>类型</th><th>方向</th><th>数量</th><th>结存</th><th>操作人</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="f in flows" :key="f.tx_no">
            <td>{{ f.tx_no }}</td>
            <td>{{ f.tx_type }}</td>
            <td><span class="tag" :class="f.direction === 1 ? 'tag-success' : 'tag-warn'">{{ f.direction === 1 ? '入库' : '出库' }}</span></td>
            <td>{{ num(f.qty, 2) }}</td>
            <td>{{ num(f.balance_after, 2) }}</td>
            <td>{{ f.operator_no || '—' }}</td>
            <td>{{ f.tx_time ? String(f.tx_time).replace('T', ' ').slice(0, 19) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  `
}

/* ------------------------------------------------------------------ 报表 */
export const ReportsView = {
  components: { Chart },
  data() {
    return { catalog: [], active: 'work_order_progress', payload: null, days: 30, error: '' }
  },
  computed: {
    items() { return (this.payload && this.payload.items) || [] },
    chartOption() {
      const rows = this.items
      if (!rows.length) return null
      if (this.active === 'yield_rate') {
        return {
          tooltip: { trigger: 'axis' },
          legend: { data: ['良品率', '不良率'] },
          grid: { left: 58, right: 20, top: 34, bottom: 40 },
          xAxis: { type: 'category', data: rows.map((r) => r.product_code) },
          yAxis: { type: 'value', max: 100 },
          series: [
            { name: '良品率', type: 'bar', data: rows.map((r) => r.yield_rate), itemStyle: { color: '#189a5b' } },
            { name: '不良率', type: 'bar', data: rows.map((r) => r.defect_rate), itemStyle: { color: '#d3453c' } }
          ]
        }
      }
      if (this.active === 'output_daily') {
        return {
          tooltip: { trigger: 'axis' },
          legend: { data: ['合格数', '不良数'] },
          grid: { left: 58, right: 20, top: 34, bottom: 40 },
          xAxis: { type: 'category', data: rows.map((r) => r.stat_date) },
          yAxis: { type: 'value' },
          series: [
            { name: '合格数', type: 'line', data: rows.map((r) => r.qty_good), itemStyle: { color: '#2b579a' } },
            { name: '不良数', type: 'line', data: rows.map((r) => r.qty_defect), itemStyle: { color: '#d3453c' } }
          ]
        }
      }
      if (this.active === 'equipment_oee') {
        return {
          tooltip: { trigger: 'axis' },
          grid: { left: 58, right: 20, top: 28, bottom: 40 },
          xAxis: { type: 'category', data: rows.map((r) => r.equipment_code) },
          yAxis: { type: 'value', max: 100 },
          series: [{ type: 'bar', data: rows.map((r) => r.availability), itemStyle: { color: '#3f6fb5' } }]
        }
      }
      return null
    }
  },
  methods: {
    async query(code) {
      this.active = code || this.active
      this.error = ''
      try { this.payload = await api.reportQuery(this.active, { days: this.days }) }
      catch (e) { this.payload = null; this.error = e.message }
    }
  },
  async mounted() {
    this.catalog = await api.reportCatalog()
    await this.query()
  },
  template: `
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div class="card">
      <div class="card-head">
        <h2>统计报表（8 张）</h2>
        <select v-model.number="days" @change="query()">
          <option :value="7">近 7 天</option><option :value="30">近 30 天</option><option :value="90">近 90 天</option>
        </select>
      </div>
      <div class="toolbar">
        <button v-for="c in catalog" :key="c.code" class="btn" :class="active === c.code ? '' : 'plain'" @click="query(c.code)">
          {{ c.name }}
        </button>
      </div>
    </div>

    <div v-if="payload" class="card">
      <div class="card-head"><h2>汇总指标</h2></div>
      <div class="grid grid-4">
        <div v-for="(v, k) in payload.summary" :key="k">
          <div class="muted small">{{ k }}</div>
          <div style="font-size:17px;font-weight:600">{{ typeof v === 'number' ? Number(v).toFixed(2) : v }}</div>
        </div>
      </div>
    </div>

    <div v-if="chartOption" class="card">
      <div class="card-head"><h2>图表视图</h2></div>
      <Chart :option="chartOption" height="290px" />
    </div>

    <div v-if="items.length" class="card">
      <div class="card-head"><h2>明细数据（{{ items.length }} 行）</h2></div>
      <table>
        <thead><tr><th v-for="(v, k) in items[0]" :key="k">{{ k }}</th></tr></thead>
        <tbody>
          <tr v-for="(row, i) in items" :key="i">
            <td v-for="(v, k) in row" :key="k">{{ typeof v === 'number' ? Number(v).toFixed(2) : v }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  `
}
