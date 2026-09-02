// 财务报表（项目书 7.5 DoD ③④）：资产负债表 + 利润表 + 期末结转 / 期间结账入口。
// - 资产负债表内置「资产 = 负债 + 所有者权益」校验，不平则顶部红条并显示差额
// - 利润表校验「净利润 = 本年利润(3103)科目发生额」，不一致提示未结转
window.ReportView = Vue.defineComponent({
  name: 'ReportView',
  data() {
    const d = new Date();
    return {
      tab: 'bs',
      year: d.getFullYear(),
      month: d.getMonth() + 1,
      monthFrom: 1,
      monthTo: d.getMonth() + 1,
      loading: false,
      bs: null,
      pl: null,
      periods: [],
      closingPeriod: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
    };
  },
  computed: {
    period() { return `${this.year}-${String(this.month).padStart(2, '0')}`; },
    periodFrom() { return `${this.year}-${String(this.monthFrom).padStart(2, '0')}`; },
    periodTo() { return `${this.year}-${String(this.monthTo).padStart(2, '0')}`; },
    monthOptions() {
      return Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `${i + 1} 月` }));
    },
  },
  watch: { tab() { this.load(); } },
  mounted() { this.load(); this.loadPeriods(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    async load() {
      this.loading = true;
      try {
        if (this.tab === 'bs') {
          this.bs = await ZCAPI.acc.balanceSheet(this.period);
        } else {
          this.pl = await ZCAPI.acc.incomeStatement(this.periodFrom, this.periodTo);
        }
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '取数失败');
        this.bs = null; this.pl = null;
      }
      this.loading = false;
    },
    async loadPeriods() {
      try {
        const r = await ZCAPI.acc.periods();
        this.periods = r.periods || [];
      } catch (e) { this.periods = []; }
    },

    async doCarryForward() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确认将 ${this.closingPeriod} 期间损益类科目余额结转到「3103 本年利润」？\n` +
          '同期间重复结转会被拦截。', '期末结转确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        const r = await ZCAPI.acc.carryForward(this.closingPeriod);
        ElementPlus.ElMessage.success(`结转完成，已生成凭证 ${r.move.name}`);
        this.load(); this.loadPeriods();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '结转失败');
      }
    },

    async togglePeriod(row) {
      try {
        if (row.closed) {
          await ZCAPI.acc.openPeriod(row.period);
          ElementPlus.ElMessage.success(`期间 ${row.period} 已解锁`);
        } else {
          await ZCAPI.acc.closePeriod(row.period, '报表页结账');
          ElementPlus.ElMessage.success(`期间 ${row.period} 已结账锁定`);
        }
        this.loadPeriods();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },
  },
  template: `
  <div>
    <!-- 资产负债表不平：顶部红条警示（DoD ③） -->
    <div v-if="bs && tab === 'bs' && !bs.balanced" class="report-alert">
      <el-icon><warning-filled></warning-filled></el-icon>
      <span>{{ bs.warning }}</span>
    </div>
    <!-- 利润表与本年利润不一致：黄条提示（DoD ④） -->
    <div v-if="pl && tab === 'pl' && !pl.consistent" class="report-alert warn">
      <el-icon><info-filled></info-filled></el-icon>
      <span>{{ pl.note }}</span>
    </div>

    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><data-analysis></data-analysis></el-icon>
          <div style="font-size:16px; font-weight:600">财务报表</div>
        </div>
        <div style="flex:1"></div>
      </div>

      <!-- 筛选区 -->
      <el-form :inline="true" size="small" style="margin: 12px 0">
        <el-form-item label="年度">
          <el-input-number v-model="year" :min="2000" :max="2099" style="width:110px"></el-input-number>
        </el-form-item>
        <el-form-item v-if="tab === 'bs'" label="期间">
          <el-select v-model="month" style="width:90px">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item v-else label="期间">
          <el-select v-model="monthFrom" style="width:90px">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
          <span style="margin:0 6px; color:var(--zc-text-2)">至</span>
          <el-select v-model="monthTo" style="width:90px">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">取数</el-button>
        </el-form-item>
      </el-form>

      <el-tabs v-model="tab">
        <!-- ============ 资产负债表 ============ -->
        <el-tab-pane label="资产负债表" name="bs">
          <div v-if="bs" v-loading="loading">
            <div class="bs-grid">
              <!-- 资产 -->
              <div class="bs-col">
                <div class="bs-col-head">资　产</div>
                <template v-for="key in ['asset_current', 'asset_noncurrent']" :key="key">
                  <div class="bs-sec-title">{{ bs.sections[key].label }}</div>
                  <div class="bs-row" v-for="it in bs.sections[key].items" :key="it.name">
                    <span>{{ it.name }}</span>
                    <span class="amt">{{ fmt(it.amount) }}</span>
                  </div>
                  <div class="bs-subtotal">
                    <span>{{ bs.sections[key].label }}合计</span>
                    <span class="amt">{{ fmt(bs.sections[key].total) }}</span>
                  </div>
                </template>
                <div class="bs-total">
                  <span>资产总计</span>
                  <span class="amt">{{ fmt(bs.total_assets) }}</span>
                </div>
              </div>

              <!-- 负债与权益 -->
              <div class="bs-col">
                <div class="bs-col-head">负债和所有者权益</div>
                <template v-for="key in ['liability_current', 'liability_noncurrent']" :key="key">
                  <div class="bs-sec-title">{{ bs.sections[key].label }}</div>
                  <div class="bs-row" v-for="it in bs.sections[key].items" :key="it.name">
                    <span>{{ it.name }}</span>
                    <span class="amt">{{ fmt(it.amount) }}</span>
                  </div>
                  <div class="bs-subtotal">
                    <span>{{ bs.sections[key].label }}合计</span>
                    <span class="amt">{{ fmt(bs.sections[key].total) }}</span>
                  </div>
                </template>
                <div class="bs-sec-title">所有者权益</div>
                <div class="bs-row" v-for="it in bs.sections.equity.items" :key="it.name">
                  <span>{{ it.name }}</span>
                  <span class="amt">{{ fmt(it.amount) }}</span>
                </div>
                <div class="bs-subtotal">
                  <span>所有者权益合计</span>
                  <span class="amt">{{ fmt(bs.total_equity) }}</span>
                </div>
                <div class="bs-total">
                  <span>负债和所有者权益总计</span>
                  <span class="amt">{{ fmt(bs.total_liab_equity) }}</span>
                </div>
              </div>
            </div>

            <div class="ledger-total-line" style="margin-top:12px">
              平衡校验：资产总计 <b>{{ fmt(bs.total_assets) }}</b>
              ／ 负债和所有者权益总计 <b>{{ fmt(bs.total_liab_equity) }}</b>
              <el-tag size="small" :type="bs.balanced ? 'success' : 'danger'" style="margin-left:10px">
                {{ bs.balanced ? '平衡' : '差额 ' + fmt(bs.diff) }}
              </el-tag>
            </div>
          </div>
          <el-empty v-else description="暂无数据"></el-empty>
        </el-tab-pane>

        <!-- ============ 利润表 ============ -->
        <el-tab-pane label="利润表" name="pl">
          <div v-if="pl" v-loading="loading">
            <el-table :data="pl.rows" border size="small">
              <el-table-column prop="name" label="项目" min-width="300"></el-table-column>
              <el-table-column label="本期金额" width="180" align="right">
                <template #default="{ row }">
                  <b v-if="row.type === 'formula'">{{ fmt(row.amount) }}</b>
                  <span v-else>{{ fmt(row.amount) }}</span>
                </template>
              </el-table-column>
            </el-table>

            <div class="ledger-total-line" style="margin-top:12px">
              净利润 <b>{{ fmt(pl.net_profit) }}</b>
              ／ 本年利润(3103)科目发生额 <b>{{ fmt(pl.profit_account_move) }}</b>
              <el-tag size="small" :type="pl.consistent ? 'success' : 'warning'" style="margin-left:10px">
                {{ pl.consistent ? '一致' : '不一致' }}
              </el-tag>
              <span v-if="!pl.consistent" style="font-size:12px; color:var(--zc-text-2); margin-left:8px">
                通常是因为该期间尚未做期末结转
              </span>
            </div>
          </div>
          <el-empty v-else description="暂无数据"></el-empty>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 期末处理 -->
    <div class="view-card" style="margin-top:14px">
      <div class="form-head">
        <div style="font-size:15px; font-weight:600">期末处理</div>
      </div>
      <el-form :inline="true" size="small" style="margin: 12px 0">
        <el-form-item label="结转期间">
          <el-input v-model="closingPeriod" style="width:120px" placeholder="YYYY-MM"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="doCarryForward">
            <el-icon><refresh></refresh></el-icon> 一键结转损益
          </el-button>
        </el-form-item>
      </el-form>

      <div style="font-size:13px; font-weight:600; margin-bottom:8px">期间结账状态</div>
      <el-table :data="periods" border size="small" max-height="260">
        <el-table-column prop="period" label="期间" width="120"></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.closed ? 'danger' : 'success'">
              {{ row.closed ? '已结账' : '未结账' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="closed_at" label="结账时间" width="180"></el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link :type="row.closed ? 'warning' : 'primary'" @click="togglePeriod(row)">
              {{ row.closed ? '解锁期间' : '结账锁定' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
  `,
});
