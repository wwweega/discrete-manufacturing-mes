/** 展示层格式化工具。 */
export function pct(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${Number(value).toFixed(digits)}%`
}

export function num(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return Number(value).toFixed(digits)
}

export function dateText(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

export function shortText(value, length = 28) {
  const text = String(value ?? '')
  return text.length > length ? `${text.slice(0, length)}…` : text
}

/** 工单状态 → 中文 + 语义色（红=告警/停滞，绿=正常/完成，蓝=进行中）。 */
export const ORDER_STATUS = {
  DRAFT: { label: '草稿', tone: 'muted' },
  RELEASED: { label: '已下达', tone: 'info' },
  IN_PROGRESS: { label: '生产中', tone: 'primary' },
  PAUSED: { label: '暂停', tone: 'warn' },
  COMPLETED: { label: '已完工', tone: 'success' },
  CANCELLED: { label: '已作废', tone: 'danger' }
}

export const OP_STATUS = {
  NOT_STARTED: { label: '未开工', tone: 'muted' },
  RUNNING: { label: '加工中', tone: 'primary' },
  FINISHED: { label: '已完成', tone: 'success' }
}

export const QC_STATUS = {
  PENDING: { label: '待处理', tone: 'warn' },
  TESTING: { label: '检验中', tone: 'primary' },
  PASSED: { label: '合格', tone: 'success' },
  FAILED: { label: '不合格', tone: 'danger' },
  CLOSED: { label: '已关闭', tone: 'muted' }
}

export const EQUIP_STATUS = {
  RUN: { label: '运行', tone: 'success' },
  IDLE: { label: '待机', tone: 'muted' },
  FAULT: { label: '故障', tone: 'danger' },
  MAINTAIN: { label: '维保', tone: 'warn' },
  OFFLINE: { label: '离线', tone: 'muted' }
}

export const TX_TYPE = {
  PURCHASE_IN: '采购入库',
  WO_ISSUE: '工单领料',
  RETURN: '退料',
  FINISH_IN: '完工入库',
  ADJUST: '盘点调整',
  SCRAP_OUT: '报废出库'
}

/** 已被后端接收的状态，用于渲染流转按钮。 */
export function statusLabel(map, value) {
  return map[value]?.label ?? value ?? '-'
}

export function statusTone(map, value) {
  return map[value]?.tone ?? 'muted'
}
