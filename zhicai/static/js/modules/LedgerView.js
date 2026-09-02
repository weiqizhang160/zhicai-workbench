// 账簿查询（项目书 7.5）：总账 / 明细账 / 科目余额表，支持期间区间与 CSV 导出。
// 口径：只有已过账（posted）凭证计入账务，草稿不进账。
window.LedgerView = Vue.defineComponent({
  name: 'LedgerView',
  data() {
    const d = new Date();
    return {
      tab: 'trial',                 // trial / general / subsidiary
      year: d.getFullYear(),
      monthFrom: 1,
      monthTo: d.getMonth() + 1,
      loading: false,
      accounts: [],
      selAccountId: null,
      rows: [],
      totals: null,
      sub: null,                    // 明细账结果
    };
  },
  computed: {
    periodFrom() { return `${this.year}-${String(this.monthFrom).padStart(2, '0')}`; },
    periodTo() { return `${this.year}-${String(this.monthTo).padStart(2, '0')}`; },
    monthOptions() {
      return Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }));
    },
  },
  watch: {
    tab() { this.load(); },
    selAccountId() { if (this.tab === 'subsidiary') this.load(); },
  },
  mounted() {
    this.loadAccounts();
    this.load();
  },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    async loadAccounts() {
      try {
        const r = await ZCAPI.acc.leafAccounts('');
        this.accounts = r.accounts || [];
        if (this.accounts.length && !this.selAccountId) {
          this.selAccountId = this.accounts[0].id;
        }
      } catch (e) { /* 未选账套时静默 */ }
    },

    async load() {
      this.loading = true;
      try {
        if (this.tab === 'trial') {
          const r = await ZCAPI.acc.trialBalance({ period_from: this.periodFrom,
                                                   period_to: this.periodTo });
          this.rows = r.rows || [];
          this.totals = r.totals || null;
        } else if (this.tab === 'general') {
          const r = await ZCAPI.acc.generalLedger({ period_from: this.periodFrom,
                                                    period_to: this.periodTo });
          this.rows = r.rows || [];
        } else {
          if (!this.selAccountId) { this.sub = null; this.loading = false; return; }
          this.sub = await ZCAPI.acc.subsidiaryLedger({
            account_id: this.selAccountId,
            period_from: this.periodFrom, period_to: this.periodTo,
          });
        }
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '查询失败');
        this.rows = []; this.sub = null;
      }
      this.loading = false;
    },

    // 导出 CSV（Excel 可直接打开，带 BOM 防中文乱码）
    exportCsv() {
      let head, rows;
      if (this.tab === 'trial') {
        head = ['科目编码', '科目名称', '方向', '期初余额', '本期借方', '本期贷方', '期末余额',
                '借方余额', '贷方余额'];
        rows = this.rows.map((r) => [r.code, r.name, r.direction === 'debit' ? '借' : '贷',
                                     r.opening, r.debit, r.credit, r.ending,
                                     r.debit_balance, r.credit_balance]);
      } else if (this.tab === 'general') {
        head = ['科目编码', '科目名称', '方向', '期初余额', '本期借方', '本期贷方', '期末余额'];
        rows = this.rows.map((r) => [r.code, r.name, r.direction === 'debit' ? '借' : '贷',
                                     r.opening, r.debit, r.credit, r.ending]);
      } else {
        if (!this.sub) return;
        const a = this.sub.account;
        head = ['日期', '凭证号', '摘要', '借方', '贷方', '方向', '余额'];
        rows = (this.sub.items || []).map((i) => [i.move_date, i.move_name || '', i.summary,
                                                  i.debit, i.credit, i.balance_direction,
                                                  i.balance]);
      }
      const csv = [head].concat(rows)
        .map((r) => r.map((c) => `"${String(c === null || c === undefined ? '' : c)
          .replace(/"/g, '""')}"`).join(',')).join('\r\n');
      const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const nameMap = { trial: '科目余额表', general: '总账', subsidiary: '明细账' };
      a.href = url;
      a.download = `${nameMap[this.tab]}_${this.periodFrom}_${this.periodTo}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      ElementPlus.ElMessage.success('已导出 CSV');
    },

    openMove(id) { location.hash = '#/move/' + id; },
  },
  template: `
  <div class="view-card">
    <div class="form-head">
      <div style="display:flex; align-items:center; gap:10px">
        <el-icon style="font-size:22px; color:var(--zc-primary)"><reading></reading></el-icon>
        <div style="font-size:16px; font-weight:600">账簿查询</div>
      </div>
      <div style="flex:1"></div>
      <el-button size="small" :disabled="!rows.length && !sub" @click="exportCsv">
        <el-icon><download></download></el-icon> 导出 CSV
      </el-button>
    </div>

    <!-- 筛选区 -->
    <el-form :inline="true" size="small" style="margin: 12px 0">
      <el-form-item label="年度">
        <el-input-number v-model="year" :min="2000" :max="2099" style="width:110px"></el-input-number>
      </el-form-item>
      <el-form-item label="期间">
        <el-select v-model="monthFrom" style="width:90px">
          <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
        </el-select>
        <span style="margin:0 6px; color:var(--zc-text-2)">至</span>
        <el-select v-model="monthTo" style="width:90px">
          <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item v-if="tab === 'subsidiary'" label="科目">
        <el-select v-model="selAccountId" filterable style="width:260px">
          <el-option v-for="a in accounts" :key="a.id" :label="a.display" :value="a.id"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="load">查询</el-button>
      </el-form-item>
    </el-form>

    <el-tabs v-model="tab">
      <!-- 科目余额表 -->
      <el-tab-pane label="科目余额表" name="trial">
        <el-table :data="rows" border size="small" height="520" v-loading="loading">
          <el-table-column prop="code" label="科目编码" width="110"></el-table-column>
          <el-table-column prop="name" label="科目名称" min-width="160"></el-table-column>
          <el-table-column label="方向" width="60" align="center">
            <template #default="{ row }">{{ row.direction === 'debit' ? '借' : '贷' }}</template>
          </el-table-column>
          <el-table-column label="期初余额" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.opening) }}</template>
          </el-table-column>
          <el-table-column label="本期借方" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.debit) }}</template>
          </el-table-column>
          <el-table-column label="本期贷方" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.credit) }}</template>
          </el-table-column>
          <el-table-column label="期末余额" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.ending) }}</template>
          </el-table-column>
          <el-table-column label="借方余额" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.debit_balance) }}</template>
          </el-table-column>
          <el-table-column label="贷方余额" width="120" align="right">
            <template #default="{ row }">{{ fmt(row.credit_balance) }}</template>
          </el-table-column>
        </el-table>
        <div v-if="totals" class="ledger-total-line">
          合计：借方余额 <b>{{ fmt(totals.debit_balance) }}</b>
          ／ 贷方余额 <b>{{ fmt(totals.credit_balance) }}</b>
          <el-tag size="small" :type="totals.debit_balance === totals.credit_balance ? 'success' : 'danger'"
                  style="margin-left:10px">
            {{ totals.debit_balance === totals.credit_balance ? '借贷平衡' : '不平衡' }}
          </el-tag>
          <span style="font-size:12px; color:var(--zc-text-2); margin-left:8px">
            （合计仅累加末级科目，父科目余额为下级汇总，不重复计入）
          </span>
        </div>
      </el-tab-pane>

      <!-- 总账 -->
      <el-tab-pane label="总账" name="general">
        <el-table :data="rows" border size="small" height="520" v-loading="loading">
          <el-table-column prop="code" label="科目编码" width="110"></el-table-column>
          <el-table-column prop="name" label="科目名称" min-width="180"></el-table-column>
          <el-table-column label="期初余额" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.opening) }}</template>
          </el-table-column>
          <el-table-column label="本期借方" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.debit) }}</template>
          </el-table-column>
          <el-table-column label="本期贷方" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.credit) }}</template>
          </el-table-column>
          <el-table-column label="期末余额" width="130" align="right">
            <template #default="{ row }">{{ fmt(row.ending) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 明细账 -->
      <el-tab-pane label="明细账" name="subsidiary">
        <div v-if="sub" style="margin-bottom:10px">
          <div style="font-size:14px; font-weight:600; margin-bottom:6px">
            {{ sub.account.code }} {{ sub.account.name }}
            <el-tag size="small" style="margin-left:6px">
              {{ sub.account.direction === 'debit' ? '借方' : '贷方' }}余额
            </el-tag>
          </div>
          <el-table :data="sub.items" border size="small" height="470" v-loading="loading">
            <el-table-column prop="move_date" label="日期" width="110"></el-table-column>
            <el-table-column label="凭证号" width="140">
              <template #default="{ row }">
                <el-link type="primary" @click="openMove(row.move_id)">{{ row.move_name || '—' }}</el-link>
              </template>
            </el-table-column>
            <el-table-column prop="summary" label="摘要" min-width="180"></el-table-column>
            <el-table-column label="借方" width="120" align="right">
              <template #default="{ row }">{{ fmt(row.debit) }}</template>
            </el-table-column>
            <el-table-column label="贷方" width="120" align="right">
              <template #default="{ row }">{{ fmt(row.credit) }}</template>
            </el-table-column>
            <el-table-column label="方向" width="60" align="center">
              <template #default="{ row }">{{ row.balance_direction }}</template>
            </el-table-column>
            <el-table-column label="余额" width="130" align="right">
              <template #default="{ row }">{{ fmt(row.balance) }}</template>
            </el-table-column>
          </el-table>
          <div class="ledger-total-line">
            期初 <b>{{ fmt(sub.opening) }}</b>
            ／ 本期借方 <b>{{ fmt(sub.total_debit) }}</b>
            ／ 本期贷方 <b>{{ fmt(sub.total_credit) }}</b>
            ／ 期末 <b>{{ fmt(sub.ending) }}</b>
          </div>
        </div>
        <el-empty v-else description="请选择科目后查询"></el-empty>
      </el-tab-pane>
    </el-tabs>
  </div>
  `,
});
