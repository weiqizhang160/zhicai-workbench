// 合同与收费管理（项目书 7.4）——合同列表 + 收费计划 + 收款登记 + 应收报表。
// 状态流转 unpaid→invoiced→paid；逾期由扫描任务标 overdue 并生成催收任务；
// 合同到期前 30 天生成续约提醒任务。
window.ContractView = Vue.defineComponent({
  name: 'ContractView',
  data() {
    const d = new Date();
    return {
      tab: 'agreements',      // agreements / collect / report
      agreements: [],
      feeItems: [],
      report: null,
      loading: false,
      scanning: false,

      // 筛选
      agState: '',
      feeState: '',
      overdueOnly: false,
      collectPeriod: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,

      // 合同详情抽屉
      drawer: false,
      curAgreement: null,
      curFeeItems: [],
      generating: false,

      // 新建合同
      newDialog: false,
      newForm: null,
      newSubmitting: false,

      // 收款登记多选
      selection: [],
    };
  },
  computed: {
    feeTypeLabel() {
      return { monthly: '按月', quarterly: '按季', annual: '按年' };
    },
    serviceScopeOptions() {
      return [
        { value: 'bookkeeping', label: '代理记账' },
        { value: 'tax_return', label: '纳税申报' },
        { value: 'annual_inspection', label: '工商年检' },
        { value: 'export_refund', label: '出口退税' },
        { value: 'payroll', label: '工资代发' },
        { value: 'other', label: '其他' },
      ];
    },
  },
  watch: {
    tab() { this.load(); },
    overdueOnly() { this.loadFee(); },
    feeState() { this.loadFee(); },
  },
  mounted() { this.load(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    feeTypeText(t) { return this.feeTypeLabel[t] || t; },
    scopeText(scope) {
      if (!scope) return '—';
      const arr = Array.isArray(scope) ? scope : [];
      const map = {};
      this.serviceScopeOptions.forEach((o) => { map[o.value] = o.label; });
      return arr.map((v) => map[v] || v).join('、') || '—';
    },
    stateInfo(kind, v) {
      return window.zcState ? window.zcState(kind, v) : { label: v, color: '#6C757D' };
    },

    async load() {
      this.loading = true;
      try {
        await Promise.all([this.loadAgreements(), this.loadFee(), this.loadReport()]);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      }
      this.loading = false;
    },
    async loadAgreements() {
      const r = await ZCAPI.contract.agreements({ state: this.agState, limit: 300 });
      this.agreements = r.agreements || [];
    },
    async loadFee() {
      const r = await ZCAPI.contract.feeItems({
        state: this.feeState, overdue_only: this.overdueOnly, limit: 2000,
      });
      this.feeItems = r.items || [];
    },
    async loadReport() {
      const r = await ZCAPI.contract.receivable();
      this.report = r;
    },

    // ---------- 合同详情抽屉 ----------
    async openDetail(row) {
      this.curAgreement = row;
      this.drawer = true;
      this.curFeeItems = [];
      try {
        const r = await ZCAPI.contract.agreement(row.id);
        this.curAgreement = r.agreement;
        this.curFeeItems = r.fee_items || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '读取合同失败');
      }
    },
    async doGenerate() {
      if (!this.curAgreement) return;
      this.generating = true;
      try {
        const r = await ZCAPI.contract.generateFee(this.curAgreement.id);
        ElementPlus.ElMessage.success(
          `生成完成：新建 ${r.created} 期${r.skipped ? `，跳过 ${r.skipped} 期（已存在）` : ''}`);
        const d = await ZCAPI.contract.agreement(this.curAgreement.id);
        this.curAgreement = d.agreement;
        this.curFeeItems = d.fee_items || [];
        this.loadFee();
        this.loadReport();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '生成失败');
      }
      this.generating = false;
    },

    // ---------- 新建合同 ----------
    openNew() {
      this.newDialog = true;
      this.newForm = {
        book_id: (window.ZC_STORE && window.ZC_STORE.currentBookId) || null,
        sign_date: new Date().toISOString().slice(0, 10),
        start_date: new Date().toISOString().slice(0, 10),
        end_date: new Date(new Date().getFullYear() + 1, new Date().getMonth(), new Date().getDate())
          .toISOString().slice(0, 10),
        service_scope: ['bookkeeping', 'tax_return'],
        fee_type: 'monthly',
        fee_amount: '',
        payer_name: '',
        remark: '',
      };
    },
    async submitNew() {
      const f = this.newForm;
      if (!f.book_id) return ElementPlus.ElMessage.warning('请先选择客户账套（右上角切换器）');
      if (!f.start_date || !f.end_date) return ElementPlus.ElMessage.warning('请填写服务起止日期');
      if (!f.fee_amount || parseFloat(f.fee_amount) <= 0) return ElementPlus.ElMessage.warning('请填写每期金额');
      this.newSubmitting = true;
      try {
        const r = await ZCAPI.contract.createAgreement(f);
        ElementPlus.ElMessage.success(`合同 ${r.agreement.contract_no} 已创建，自动生成 ${r.fee.created} 期收费计划`);
        this.newDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '创建失败');
      }
      this.newSubmitting = false;
    },

    // ---------- 收款登记 ----------
    async bulkCollect() {
      if (!this.selection.length) return ElementPlus.ElMessage.warning('请先勾选要收款的收费计划');
      const rows = this.feeItems.filter((f) => this.selection.includes(f.id));
      const unpaid = rows.filter((f) => f.state !== 'paid');
      if (!unpaid.length) return ElementPlus.ElMessage.warning('所选项目均已收款');
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确认将 ${unpaid.length} 期收费计划标记为已收款？合计 ¥${this.fmt(unpaid.reduce((s, f) => s + parseFloat(f.amount), 0))}`,
          '批量收款登记', { type: 'warning', confirmButtonText: '确认收款', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        const r = await ZCAPI.contract.bulkCollect(this.selection);
        ElementPlus.ElMessage.success(`已收款 ${r.collected} 期`);
        this.selection = [];
        await this.loadFee();
        await this.loadReport();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '收款登记失败');
      }
    },
    async collectOne(row) {
      try {
        await ZCAPI.contract.collect(row.id);
        ElementPlus.ElMessage.success('已标记收款');
        await this.loadFee();
        await this.loadReport();
        if (this.drawer) await this.openDetail(this.curAgreement);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },
    async invoiceOne(row) {
      try {
        const { value } = await ElementPlus.ElMessageBox.prompt(
          '请输入发票号码（可留空）', '标记已开票', { confirmButtonText: '确认', cancelButtonText: '取消' });
        await ZCAPI.contract.invoice(row.id, value || '');
        ElementPlus.ElMessage.success('已标记开票');
        await this.loadFee();
      } catch (e) { /* 取消或失败 */ }
    },

    // ---------- 逾期/续约扫描 ----------
    async doScan() {
      this.scanning = true;
      try {
        const r = await ZCAPI.contract.scan();
        ElementPlus.ElMessage.success(
          `扫描完成：逾期 ${r.overdue_marked} 期，新增催收任务 ${r.collection_tasks} 条、续约提醒 ${r.renewal_tasks} 条`);
        await this.loadFee();
        await this.loadAgreements();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '扫描失败');
      }
      this.scanning = false;
    },

    goTasks() { location.hash = '#/tasks'; },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><document></document></el-icon>
          <div>
            <div style="font-size:16px; font-weight:600">合同与收费管理</div>
            <div style="font-size:12px; color:var(--zc-text-2)">
              到期前 30 天自动提醒续约 · 逾期自动生成催收任务 · 月末一键批量收款
            </div>
          </div>
        </div>
        <div style="flex:1"></div>
        <el-button size="small" @click="doScan" :loading="scanning">
          <el-icon><bell></bell></el-icon> 扫描逾期/续约
        </el-button>
        <el-button size="small" type="primary" @click="openNew">
          <el-icon><plus></plus></el-icon> 新建合同
        </el-button>
      </div>

      <el-tabs v-model="tab" style="margin-top:8px">
        <!-- 合同列表 -->
        <el-tab-pane label="合同列表" name="agreements">
          <el-form :inline="true" size="small" style="margin-bottom:10px">
            <el-form-item label="状态">
              <el-select v-model="agState" clearable style="width:120px" @change="loadAgreements">
                <el-option label="履行中" value="active"></el-option>
                <el-option label="已到期" value="expired"></el-option>
                <el-option label="已终止" value="terminated"></el-option>
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="loadAgreements">查询</el-button>
            </el-form-item>
          </el-form>
          <el-table :data="agreements" border size="small" v-loading="loading" height="440">
            <el-table-column prop="contract_no" label="合同编号" width="110"></el-table-column>
            <el-table-column prop="book_name" label="客户" width="140"></el-table-column>
            <el-table-column label="服务范围" min-width="180">
              <template #default="{ row }">{{ scopeText(row.service_scope) }}</template>
            </el-table-column>
            <el-table-column label="周期" width="80">
              <template #default="{ row }">{{ feeTypeText(row.fee_type) }}</template>
            </el-table-column>
            <el-table-column label="每期金额" width="110" align="right">
              <template #default="{ row }">¥{{ fmt(row.fee_amount) }}</template>
            </el-table-column>
            <el-table-column label="起止日期" width="200">
              <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :color="stateInfo('agreement_state', row.state).color" style="color:#fff;border:none">
                  {{ stateInfo('agreement_state', row.state).label }}
                </el-tag>
                <el-tag v-if="row.expiring" size="small" type="warning" style="margin-left:4px">临期</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">收费计划</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 收款登记 -->
        <el-tab-pane label="收款登记" name="collect">
          <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px">
            <el-checkbox v-model="overdueOnly">只看逾期</el-checkbox>
            <el-select v-model="feeState" clearable placeholder="状态筛选" style="width:130px" size="small">
              <el-option label="未收款" value="unpaid"></el-option>
              <el-option label="已开票" value="invoiced"></el-option>
              <el-option label="已收款" value="paid"></el-option>
              <el-option label="已逾期" value="overdue"></el-option>
            </el-select>
            <div style="flex:1"></div>
            <span v-if="selection.length" style="font-size:13px;color:var(--zc-text-2)">
              已选 {{ selection.length }} 期
            </span>
            <el-button size="small" type="success" :disabled="!selection.length" @click="bulkCollect">
              <el-icon><checked></el-icon> 批量收款
            </el-button>
          </div>
          <el-table :data="feeItems" border size="small" v-loading="loading" height="440"
                    @selection-change="(rows) => selection = rows.map(r => r.id)">
            <el-table-column type="selection" width="40"></el-table-column>
            <el-table-column prop="period" label="收费期" width="90"></el-table-column>
            <el-table-column prop="book_name" label="客户" width="140"></el-table-column>
            <el-table-column label="应收" width="110" align="right">
              <template #default="{ row }">¥{{ fmt(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="due_date" label="到期日" width="110"></el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" :color="stateInfo('fee_state', row.state).color" style="color:#fff;border:none">
                  {{ stateInfo('fee_state', row.state).label }}
                </el-tag>
                <el-tag v-if="row.overdue && row.state !== 'paid'" size="small" type="danger" style="margin-left:4px">逾期</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="paid_date" label="收款日" width="110"></el-table-column>
            <el-table-column prop="invoice_no" label="发票号" width="130"></el-table-column>
            <el-table-column label="操作" min-width="160" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.state !== 'paid'" link type="success" @click="collectOne(row)">收款</el-button>
                <el-button v-if="row.state === 'unpaid'" link type="primary" @click="invoiceOne(row)">开票</el-button>
                <span v-if="row.state === 'paid'" style="color:var(--zc-text-3);font-size:12px">已结清</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 应收报表 -->
        <el-tab-pane label="应收报表" name="report">
          <template v-if="report">
            <div class="ledger-total-line" style="margin-bottom:12px">
              本年度已收合计 <b style="color:var(--zc-success)">¥{{ fmt(report.year_received) }}</b>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px">
              <div>
                <div style="font-size:14px;font-weight:600;margin-bottom:8px">按客户</div>
                <el-table :data="report.by_book" border size="small" max-height="380">
                  <el-table-column prop="book_name" label="客户" min-width="140"></el-table-column>
                  <el-table-column label="应收" width="110" align="right">
                    <template #default="{ row }">¥{{ fmt(row.receivable) }}</template>
                  </el-table-column>
                  <el-table-column label="已收" width="110" align="right">
                    <template #default="{ row }">¥{{ fmt(row.received) }}</template>
                  </el-table-column>
                  <el-table-column label="逾期" width="110" align="right">
                    <template #default="{ row }">
                      <span :style="parseFloat(row.overdue) > 0 ? 'color:var(--zc-danger);font-weight:600' : ''">
                        ¥{{ fmt(row.overdue) }}
                      </span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
              <div>
                <div style="font-size:14px;font-weight:600;margin-bottom:8px">按月份</div>
                <el-table :data="report.by_month" border size="small" max-height="380">
                  <el-table-column prop="period" label="收费期" width="100"></el-table-column>
                  <el-table-column label="应收" width="110" align="right">
                    <template #default="{ row }">¥{{ fmt(row.receivable) }}</template>
                  </el-table-column>
                  <el-table-column label="已收" width="110" align="right">
                    <template #default="{ row }">¥{{ fmt(row.received) }}</template>
                  </el-table-column>
                  <el-table-column label="逾期" width="110" align="right">
                    <template #default="{ row }">¥{{ fmt(row.overdue) }}</template>
                  </el-table-column>
                </el-table>
              </div>
            </div>
          </template>
          <div v-else class="bank-empty">暂无数据</div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 合同详情抽屉 -->
    <el-drawer v-model="drawer" :title="'合同 ' + (curAgreement ? curAgreement.contract_no : '')" size="52%">
      <div v-if="curAgreement">
        <div class="ledger-total-line" style="margin-bottom:12px">
          <b>{{ curAgreement.book_name }}</b> · {{ scopeText(curAgreement.service_scope) }} ·
          {{ feeTypeText(curAgreement.fee_type) }} ¥{{ fmt(curAgreement.fee_amount) }}/期 ·
          {{ curAgreement.start_date }} ~ {{ curAgreement.end_date }}
        </div>
        <div style="margin-bottom:12px">
          <el-button type="primary" size="small" :loading="generating" @click="doGenerate">
            <el-icon><refresh></refresh></el-icon> 生成收费计划
          </el-button>
          <span style="font-size:12px;color:var(--zc-text-2);margin-left:8px">幂等：已存在的期自动跳过</span>
        </div>
        <el-table :data="curFeeItems" border size="small" max-height="460">
          <el-table-column prop="period" label="收费期" width="90"></el-table-column>
          <el-table-column label="应收" width="100" align="right">
            <template #default="{ row }">¥{{ fmt(row.amount) }}</template>
          </el-table-column>
          <el-table-column prop="due_date" label="到期日" width="110"></el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :color="stateInfo('fee_state', row.state).color" style="color:#fff;border:none">
                {{ stateInfo('fee_state', row.state).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="paid_date" label="收款日" width="110"></el-table-column>
          <el-table-column label="操作" min-width="120">
            <template #default="{ row }">
              <el-button v-if="row.state !== 'paid'" link type="success" @click="collectOne(row)">收款</el-button>
              <span v-else style="color:var(--zc-text-3);font-size:12px">已结清</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-drawer>

    <!-- 新建合同弹窗 -->
    <el-dialog v-model="newDialog" title="新建代账合同" width="560px">
      <el-form v-if="newForm" label-position="top" size="small">
        <el-form-item label="客户账套" required>
          <el-select v-model="newForm.book_id" filterable style="width:100%" placeholder="选择客户">
            <el-option v-for="b in (window.ZC_STORE ? ZC_STORE.books : [])" :key="b.id"
                       :value="b.id" :label="b.code + ' ' + b.short_name"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="签订日期">
              <el-date-picker v-model="newForm.sign_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="服务开始" required>
              <el-date-picker v-model="newForm.start_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="服务结束" required>
              <el-date-picker v-model="newForm.end_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="服务范围">
          <el-checkbox-group v-model="newForm.service_scope">
            <el-checkbox v-for="o in serviceScopeOptions" :key="o.value" :label="o.value">{{ o.label }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="10">
            <el-form-item label="收费周期">
              <el-select v-model="newForm.fee_type" style="width:100%">
                <el-option label="按月" value="monthly"></el-option>
                <el-option label="按季" value="quarterly"></el-option>
                <el-option label="按年" value="annual"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="14">
            <el-form-item label="每期金额（元）" required>
              <el-input-number v-model="newForm.fee_amount" :min="0" :precision="2" style="width:100%"></el-input-number>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="付款方">
          <el-input v-model="newForm.payer_name" placeholder="如：XX 有限公司（法人 刘锦）"></el-input>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="newForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newDialog = false">取消</el-button>
        <el-button type="primary" :loading="newSubmitting" @click="submitNew">创建并生成收费计划</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
