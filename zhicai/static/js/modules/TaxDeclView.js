// 申报台账与日历（项目书 7.9）——防漏报核心页。
// 月历 / 列表双视图；状态颜色：pending 灰 / preparing 蓝 / submitted 橙 /
// paid 绿 / exempt 白 / 逾期红。计算底稿抽屉可穿透到发票与凭证。
// **系统不做自动申报**，只做登记、计算与官网导航。
window.TaxDeclView = Vue.defineComponent({
  name: 'TaxDeclView',
  data() {
    const d = new Date();
    return {
      view: 'list',            // list / calendar
      month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      taxKind: '',
      stateFilter: '',
      overdueOnly: false,
      items: [],
      dayMap: {},
      stats: null,
      loading: false,
      generating: false,

      // 计算底稿抽屉
      drawer: false,
      snapshot: null,
      curItem: null,

      // 操作弹窗
      opDialog: false,
      opType: '',              // submit / pay / exempt
      opAmount: '',
      opDate: '',
      opReason: '',
      opZero: false,

      links: {},
      genPeriod: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
    };
  },
  computed: {
    monthOptions() {
      const y = new Date().getFullYear();
      return Array.from({ length: 12 }, (_, i) => ({
        value: `${y}-${String(i + 1).padStart(2, '0')}`, label: `${i + 1} 月`,
      }));
    },
    overdueCount() { return this.items.filter((i) => i.overdue).length; },
    opTitle() {
      return { submit: '标记已申报', pay: '标记已缴款', exempt: '免税 / 零申报' }[this.opType] || '操作';
    },
  },
  watch: {
    view() { this.load(); },
    overdueOnly() { this.load(); },
    stateFilter() { this.load(); },
    taxKind() { this.load(); },
  },
  mounted() { this.load(); this.loadLinks(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    kindLabel(k) {
      return ({ vat: '增值税', surtax: '附加税', cit_quarterly: '所得税(季)',
                cit_annual: '所得税(年报)', iit: '个人所得税',
                stamp: '印花税' })[k] || k;
    },
    stateLabel(s) {
      return ({ pending: '待申报', preparing: '准备中', submitted: '已申报',
                paid: '已缴款', done: '已完成', exempt: '免税/零申报' })[s] || s;
    },
    stateTagType(s) {
      // 项目书 7.9 颜色规范
      return ({ pending: 'info', preparing: 'primary', submitted: 'warning',
                paid: 'success', done: 'success', exempt: '' })[s] || 'info';
    },

    async load() {
      this.loading = true;
      try {
        if (this.view === 'calendar') {
          const r = await ZCAPI.tax.calendar(this.month);
          this.dayMap = r.days || {};
          this.stats = r.stats || null;
          this.items = [];
          for (const list of Object.values(this.dayMap)) this.items.push(...list);
        } else {
          const r = await ZCAPI.tax.items({
            due_month: this.month, tax_kind: this.taxKind,
            state: this.stateFilter, overdue_only: this.overdueOnly, limit: 500,
          });
          this.items = r.items || [];
          this.dayMap = {};
          this.stats = null;
        }
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
        this.items = [];
      }
      this.loading = false;
    },
    async loadLinks() {
      try {
        const r = await ZCAPI.tax.links();
        this.links = r.links || {};
      } catch (e) { this.links = {}; }
    },

    async doGenerate() {
      if (!this.genPeriod) return ElementPlus.ElMessage.warning('请填写属期');
      this.generating = true;
      try {
        const r = await ZCAPI.tax.generate([this.genPeriod]);
        ElementPlus.ElMessage.success(
          `生成完成：新建 ${r.created} 条${r.skipped ? `，跳过 ${r.skipped} 条（已存在）` : ''}`);
        this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '生成失败');
      }
      this.generating = false;
    },

    // ---------- 计算底稿 ----------
    async openSnapshot(row) {
      this.curItem = row;
      this.drawer = true;
      this.snapshot = null;
      try {
        const r = await ZCAPI.tax.snapshot(row.id);
        this.snapshot = r.snapshot;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '读取底稿失败');
      }
    },
    async doCompute() {
      if (!this.curItem) return;
      try {
        const r = await ZCAPI.tax.compute(this.curItem.id);
        this.snapshot = r.snapshot;
        this.curItem = r.item;
        ElementPlus.ElMessage.success('计算完成');
        this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '计算失败');
      }
    },
    // 数字穿透：跳到发票列表或科目明细账
    drill(src) {
      if (!src) return;
      if (src.type === 'invoice') {
        location.hash = `#/invoices?direction=${src.direction}&period=${src.period}`;
      } else if (src.type === 'account') {
        location.hash = '#/ledger';
      }
    },

    // ---------- 状态流转 ----------
    openOp(type, row) {
      this.curItem = row;
      this.opType = type;
      this.opAmount = row.computed_amount || '0';
      this.opDate = new Date().toISOString().slice(0, 10);
      this.opReason = '';
      this.opZero = false;
      this.opDialog = true;
    },
    async confirmOp() {
      const it = this.curItem;
      try {
        if (this.opType === 'submit') {
          if (!this.opAmount && this.opAmount !== '0') {
            return ElementPlus.ElMessage.warning('请填写实缴额');
          }
          await ZCAPI.tax.submit(it.id, this.opAmount, this.opReason);
          ElementPlus.ElMessage.success('已标记为已申报');
        } else if (this.opType === 'pay') {
          await ZCAPI.tax.pay(it.id, this.opDate);
          ElementPlus.ElMessage.success('已标记为已缴款');
        } else if (this.opType === 'exempt') {
          await ZCAPI.tax.exempt(it.id, this.opReason, this.opZero);
          ElementPlus.ElMessage.success('已标记为免税/零申报');
        }
        this.opDialog = false;
        this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },
    async backToPending(row) {
      try {
        await ZCAPI.tax.setState(row.id, 'pending');
        ElementPlus.ElMessage.success('已退回待申报');
        this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },

    openSite(taxKind) {
      const l = this.links[taxKind];
      if (l && l.url) window.open(l.url, '_blank');
      else ElementPlus.ElMessage.info('未配置该税种的官网链接，可在「参数配置」维护');
    },

    // 月历单元格内容
    cellItems(dayStr) {
      return this.dayMap[dayStr] || [];
    },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><calendar></calendar></el-icon>
          <div>
            <div style="font-size:16px; font-weight:600">申报台账与日历</div>
            <div style="font-size:12px; color:var(--zc-text-2)">
              系统只做登记与计算底稿，实际申报请点「官网直达」到电子税务局完成
            </div>
          </div>
        </div>
        <div style="flex:1"></div>
        <el-input v-model="genPeriod" placeholder="属期 YYYY-MM" style="width:140px"
                  size="small"></el-input>
        <el-button size="small" type="primary" :loading="generating" @click="doGenerate">
          <el-icon><refresh></refresh></el-icon> 批量生成台账
        </el-button>
      </div>

      <!-- 逾期警示条 -->
      <div v-if="overdueCount" class="report-alert" style="margin-top:12px">
        <el-icon><warning-filled></warning-filled></el-icon>
        <span>有 {{ overdueCount }} 项申报已逾期（截止日已过且尚未申报），请尽快处理</span>
      </div>

      <el-form :inline="true" size="small" style="margin: 12px 0">
        <el-form-item label="月份">
          <el-select v-model="month" style="width:110px" @change="load">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="税种">
          <el-select v-model="taxKind" clearable style="width:150px">
            <el-option label="增值税" value="vat"></el-option>
            <el-option label="附加税" value="surtax"></el-option>
            <el-option label="所得税(季)" value="cit_quarterly"></el-option>
            <el-option label="所得税(年报)" value="cit_annual"></el-option>
            <el-option label="个人所得税" value="iit"></el-option>
            <el-option label="印花税" value="stamp"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="stateFilter" clearable style="width:120px">
            <el-option label="待申报" value="pending"></el-option>
            <el-option label="准备中" value="preparing"></el-option>
            <el-option label="已申报" value="submitted"></el-option>
            <el-option label="已缴款" value="paid"></el-option>
            <el-option label="免税/零申报" value="exempt"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="overdueOnly">只看逾期</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">查询</el-button>
        </el-form-item>
      </el-form>

      <el-tabs v-model="view">
        <el-tab-pane label="列表视图" name="list"></el-tab-pane>
        <el-tab-pane label="月历视图" name="calendar"></el-tab-pane>
      </el-tabs>

      <!-- 列表视图 -->
      <el-table v-if="view === 'list'" :data="items" border size="small" v-loading="loading"
                height="440" :row-class-name="({row}) => row.overdue ? 'tax-overdue-row' : ''">
        <el-table-column prop="book_name" label="客户" width="120"></el-table-column>
        <el-table-column label="税种" width="110">
          <template #default="{ row }">{{ kindLabel(row.tax_kind) }}</template>
        </el-table-column>
        <el-table-column prop="period" label="属期" width="90"></el-table-column>
        <el-table-column prop="due_date" label="截止日" width="110"></el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="stateTagType(row.state)">{{ stateLabel(row.state) }}</el-tag>
            <el-tag v-if="row.overdue" size="small" type="danger" style="margin-left:4px">逾期</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="系统计算" width="120" align="right">
          <template #default="{ row }">{{ fmt(row.computed_amount) }}</template>
        </el-table-column>
        <el-table-column label="实缴额" width="110" align="right">
          <template #default="{ row }">
            {{ row.declared_amount !== null ? fmt(row.declared_amount) : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="paid_date" label="缴款日期" width="110"></el-table-column>
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSnapshot(row)">底稿</el-button>
            <el-button link type="primary" @click="openOp('submit', row)">已申报</el-button>
            <el-button link type="success" @click="openOp('pay', row)">已缴款</el-button>
            <el-button link @click="openOp('exempt', row)">免税/零申报</el-button>
            <el-button link type="warning" @click="openSite(row.tax_kind)">官网直达</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 月历视图 -->
      <div v-else v-loading="loading">
        <div v-if="stats" class="ledger-total-line" style="margin-bottom:12px">
          {{ month }} 共 <b>{{ stats.total }}</b> 项申报，
          <b style="color:var(--zc-danger)">逾期 {{ stats.overdue }}</b> ／
          待申报 {{ stats.pending || 0 }} ／ 准备中 {{ stats.preparing || 0 }} ／
          已申报 {{ stats.submitted || 0 }} ／ 已缴款 {{ stats.paid || 0 }} ／
          免税 {{ stats.exempt || 0 }}
        </div>
        <el-calendar v-model="month">
          <template #date-cell="{ data }">
            <div class="cal-cell">
              <div class="cal-day">{{ data.day.split('-')[2] }}</div>
              <div v-for="it in cellItems(data.day)" :key="it.id"
                   class="cal-item" :class="it.overdue ? 'od' : it.state"
                   :title="it.book_name + ' ' + kindLabel(it.tax_kind)"
                   @click="openSnapshot(it)">
                {{ it.book_name }}·{{ kindLabel(it.tax_kind) }}
              </div>
            </div>
          </template>
        </el-calendar>
      </div>
    </div>

    <!-- 计算底稿抽屉 -->
    <el-drawer v-model="drawer" :title="'计算底稿'" size="46%">
      <div v-if="curItem">
        <div class="ledger-total-line" style="margin-bottom:12px">
          <b>{{ curItem.book_name }}</b> · {{ kindLabel(curItem.tax_kind) }} ·
          属期 {{ curItem.period }} · 截止 {{ curItem.due_date }}
          <el-tag size="small" :type="stateTagType(curItem.state)" style="margin-left:8px">
            {{ stateLabel(curItem.state) }}
          </el-tag>
        </div>

        <div style="margin-bottom:12px">
          <el-button type="primary" size="small" @click="doCompute">
            <el-icon><refresh></refresh></el-icon> 重新计算
          </el-button>
          <el-button size="small" @click="openSite(curItem.tax_kind)">官网直达</el-button>
        </div>

        <div v-if="!snapshot" class="bank-empty" style="height:160px">
          尚未计算，点「重新计算」生成底稿
        </div>
        <div v-else>
          <div class="snap-formula">{{ snapshot.formula }}</div>
          <div v-if="snapshot.note" class="report-alert warn" style="margin:10px 0">
            <el-icon><info-filled></info-filled></el-icon><span>{{ snapshot.note }}</span>
          </div>

          <el-table :data="snapshot.items" border size="small">
            <el-table-column prop="label" label="项目" min-width="200"></el-table-column>
            <el-table-column label="金额" width="130" align="right">
              <template #default="{ row }">
                <b>{{ row.amount }}</b>
              </template>
            </el-table-column>
            <el-table-column label="取数来源" min-width="140">
              <template #default="{ row }">
                <el-link v-if="row.source" type="primary" @click="drill(row.source)">
                  {{ row.source.type === 'invoice'
                     ? ('发票·' + (row.source.direction === 'output' ? '销项' : '进项')
                        + '（' + (row.source.count || 0) + '笔）')
                     : ('科目 ' + (row.source.accounts || []).join('/')) }}
                </el-link>
                <span v-else style="color:var(--zc-text-3)">—</span>
              </template>
            </el-table-column>
          </el-table>

          <div class="ledger-total-line" style="margin-top:12px; font-size:14px">
            应纳税额 <b>{{ snapshot.result }}</b>
            <span style="font-size:12px; color:var(--zc-text-2); margin-left:8px">
              计算于 {{ snapshot.computed_at }}
            </span>
          </div>

          <div style="margin-top:14px">
            <div style="font-size:13px; font-weight:600; margin-bottom:6px">状态流转</div>
            <el-button size="small" type="primary" @click="openOp('submit', curItem)">标记已申报</el-button>
            <el-button size="small" type="success" @click="openOp('pay', curItem)">标记已缴款</el-button>
            <el-button size="small" @click="openOp('exempt', curItem)">免税/零申报</el-button>
            <el-button size="small" type="warning" @click="backToPending(curItem)">退回待申报</el-button>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 操作弹窗 -->
    <el-dialog v-model="opDialog" :title="opTitle" width="420px">
      <el-form label-position="top" size="small">
        <el-form-item v-if="opType === 'submit'" label="实缴额" required>
          <el-input v-model="opAmount" placeholder="按税局实际申报的金额填写"></el-input>
        </el-form-item>
        <el-form-item v-if="opType === 'submit'" label="备注">
          <el-input v-model="opReason" type="textarea" :rows="2"></el-input>
        </el-form-item>
        <el-form-item v-if="opType === 'pay'" label="缴款日期">
          <el-date-picker v-model="opDate" type="date" value-format="YYYY-MM-DD"
                          style="width:100%"></el-date-picker>
        </el-form-item>
        <template v-if="opType === 'exempt'">
          <el-form-item>
            <el-checkbox v-model="opZero">零申报（否则记为免税）</el-checkbox>
          </el-form-item>
          <el-form-item label="原因" required>
            <el-input v-model="opReason" type="textarea" :rows="2"
                      placeholder="如：季度销售额未达起征点"></el-input>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="opDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmOp">确认</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
