<script setup>
/** 库存：余额、流水追溯、发料/退料/盘点调整。 */
import { onMounted, reactive, ref } from 'vue'
import DataTable from '../components/DataTable.vue'
import { inventoryApi, masterApi } from '../api/modules'
import { TX_TYPE, dateText, num } from '../utils/format'
import { useAuthStore } from '../store'

const auth = useAuthStore()
const stock = ref([])
const flows = ref([])
const materials = ref([])
const warehouses = ref([])
const lowCount = ref(0)
const error = ref('')
const message = ref('')
const onlyLow = ref(false)

const form = reactive({ material_id: '', warehouse_id: '', qty: 10, target_qty: 0 })

const stockColumns = [
  { title: '物料编码', key: 'material_code' },
  { title: '物料名称', key: 'material_name' },
  { title: '仓库', key: 'warehouse_name' },
  { title: '在库量', key: 'qty_on_hand' },
  { title: '可用量', key: 'qty_available' },
  { title: '安全库存', key: 'safety_stock' },
  { title: '状态', key: 'below_safety' }
]

const flowColumns = [
  { title: '流水号', key: 'tx_no' },
  { title: '类型', key: 'tx_type' },
  { title: '方向', key: 'direction' },
  { title: '数量', key: 'qty' },
  { title: '变动后结存', key: 'balance_after' },
  { title: '来源单据', key: 'ref_id' },
  { title: '操作人', key: 'operator_no' },
  { title: '时间', key: 'tx_time' }
]

async function load() {
  try {
    const data = await inventoryApi.stock({ only_low: onlyLow.value || undefined })
    stock.value = data.items
    lowCount.value = data.low_stock_count
    flows.value = await inventoryApi.transactions({ limit: 50 })
  } catch (e) {
    error.value = e.message
  }
}

async function doAction(action) {
  message.value = ''
  try {
    if (action === 'issue') {
      await inventoryApi.issue({
        material_id: Number(form.material_id),
        warehouse_id: Number(form.warehouse_id),
        qty: Number(form.qty)
      })
      message.value = '发料成功，已生成出库流水'
    } else if (action === 'adjust') {
      await inventoryApi.adjust({
        material_id: Number(form.material_id),
        warehouse_id: Number(form.warehouse_id),
        target_qty: Number(form.target_qty)
      })
      message.value = '盘点调整完成'
    }
    await load()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(async () => {
  const master = await masterApi.all()
  materials.value = master.materials
  warehouses.value = master.warehouses
  await load()
})
</script>

<template>
  <div>
    <div v-if="error" class="alert alert-error">{{ error }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>
    <div v-if="lowCount" class="alert alert-info">
      有 {{ lowCount }} 项物料低于安全库存，建议及时补料。
    </div>

    <div class="card">
      <div class="card-head">
        <h2>库存余额</h2>
        <label class="small">
          <input v-model="onlyLow" type="checkbox" @change="load" /> 仅看低于安全库存
        </label>
      </div>
      <DataTable :columns="stockColumns" :rows="stock">
        <template #cell-below_safety="{ value }">
          <span class="tag" :class="value ? 'tag-danger' : 'tag-success'">{{ value ? '低于安全库存' : '正常' }}</span>
        </template>
        <template #cell-qty_on_hand="{ value }">{{ num(value, 2) }}</template>
        <template #cell-qty_available="{ value }">{{ num(value, 2) }}</template>
        <template #cell-safety_stock="{ value }">{{ num(value, 2) }}</template>
      </DataTable>
    </div>

    <div class="card">
      <div class="card-head"><h2>发料 / 盘点调整</h2></div>
      <div class="toolbar">
        <select v-model="form.material_id">
          <option value="">选择物料</option>
          <option v-for="m in materials" :key="m.id" :value="m.id">{{ m.code }} {{ m.name }}</option>
        </select>
        <select v-model="form.warehouse_id">
          <option value="">选择仓库</option>
          <option v-for="w in warehouses" :key="w.id" :value="w.id">{{ w.name }}</option>
        </select>
        <input v-model="form.qty" type="number" style="width: 110px" placeholder="发料数量" />
        <button v-if="auth.can('inventory:issue')" class="btn" @click="doAction('issue')">工单发料</button>
        <input v-model="form.target_qty" type="number" style="width: 130px" placeholder="调整后数量" />
        <button v-if="auth.can('inventory:adjust')" class="btn ghost" @click="doAction('adjust')">盘点调整</button>
      </div>
      <div class="small muted">库存不足时后端直接返回 409 并回滚，不会出现负库存。</div>
    </div>

    <div class="card">
      <div class="card-head"><h2>库存流水（最近 50 条）</h2></div>
      <DataTable :columns="flowColumns" :rows="flows">
        <template #cell-tx_type="{ value }">{{ TX_TYPE[value] || value }}</template>
        <template #cell-direction="{ value }">
          <span class="tag" :class="value === 1 ? 'tag-success' : 'tag-warn'">{{ value === 1 ? '入库' : '出库' }}</span>
        </template>
        <template #cell-qty="{ value }">{{ num(value, 2) }}</template>
        <template #cell-balance_after="{ value }">{{ num(value, 2) }}</template>
        <template #cell-tx_time="{ value }">{{ dateText(value) }}</template>
      </DataTable>
    </div>
  </div>
</template>
