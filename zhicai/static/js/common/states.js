// 状态颜色映射（项目书 8.4：统一放 js/common/states.js）
window.ZC_STATES = {
  // 账套服务状态
  charge_status: {
    normal:   { label: '服务中', color: '#28A745' },
    paused:   { label: '暂停',   color: '#F59E0B' },
    terminated: { label: '已终止', color: '#6C757D' },
  },
  // 纳税人类型
  taxpayer_type: {
    general:  { label: '一般纳税人', color: '#714B67' },
    small:    { label: '小规模',     color: '#17A2B8' },
  },
  // 往来单位类型
  partner_type: {
    customer: { label: '客户',     color: '#17A2B8' },
    supplier: { label: '供应商',   color: '#F59E0B' },
    both:     { label: '客户/供应商', color: '#714B67' },
  },
  // 会计准则
  accounting_standard: {
    small:      { label: '小企业会计准则', color: '#17A2B8' },
    enterprise: { label: '企业会计准则',   color: '#714B67' },
  },
  vat_period: {
    monthly:   { label: '按月', color: '#714B67' },
    quarterly: { label: '按季', color: '#17A2B8' },
  },
  journal_type: {
    general:  { label: '记账凭证', color: '#714B67' },
    receipt:  { label: '收款凭证', color: '#28A745' },
    payment:  { label: '付款凭证', color: '#DC3545' },
    transfer: { label: '转账凭证', color: '#17A2B8' },
  },
  // —— M5 合同 / 收费 / 任务 ——
  agreement_state: {
    active:     { label: '履行中', color: '#28A745' },
    expired:    { label: '已到期', color: '#F59E0B' },
    terminated: { label: '已终止', color: '#6C757D' },
  },
  fee_state: {
    unpaid:  { label: '未收款', color: '#F59E0B' },
    invoiced:{ label: '已开票', color: '#17A2B8' },
    paid:    { label: '已收款', color: '#28A745' },
    overdue: { label: '已逾期', color: '#DC3545' },
  },
  task_state: {
    todo:      { label: '待办', color: '#6C757D' },
    doing:     { label: '进行中', color: '#17A2B8' },
    done:      { label: '已完成', color: '#28A745' },
    cancelled: { label: '已取消', color: '#ADB5BD' },
  },
  task_priority: {
    low:    { label: '低', color: '#6C757D' },
    normal: { label: '普通', color: '#17A2B8' },
    high:   { label: '高', color: '#F59E0B' },
    urgent: { label: '紧急', color: '#DC3545' },
  },
};

// 通用取值函数：返回 {label, color}
window.zcState = function (kind, value) {
  const map = window.ZC_STATES[kind];
  if (!map) return { label: value == null ? '—' : String(value), color: '#6C757D' };
  const item = map[value];
  return item || { label: value == null ? '—' : String(value), color: '#6C757D' };
};
