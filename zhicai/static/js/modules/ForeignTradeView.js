// 外贸专区（项目书 6.11 / 7.10）：报关单 / 收汇结汇 / 出口退税 / 平台链接中心
// 菜单仅外贸账套存在时显示；所有写操作要求外贸账套（后端强校验）。
window.ForeignTradeView = Vue.defineComponent({
  name: 'ForeignTradeView',
  data() {
    return {
      tab: 'decls',
      loading: false,
      summary: null,
      // 报关单
      decls: [],
      declKeyword: '',
      // 收汇
      receipts: [],
      receiptKind: '',
      // 退税
      refunds: [],
      refundStatus: '',
      // 平台
      platform: null,
      platformNotes: '',
      // 弹窗
      declDialog: false,
      declForm: null,
      declSubmitting: false,
      detailDialog: false,
      detail: null,
      receiptDialog: false,
      receiptForm: null,
      refundDialog: false,
      refundForm: null,
      importDialog: false,
      importFile: null,
      importRows: null,
      importing: false,
      notesSaving: false,
    };
  },
  computed: {
    books() { return (window.ZC_STORE && window.ZC_STORE.books) || []; },
    ftBooks() { return this.books.filter((b) => b.is_foreign_trade); },
    currentBookId() { return (window.ZC_STORE && window.ZC_STORE.currentBookId) || null; },
    currentBook() { return this.books.find((b) => b.id === this.currentBookId) || null; },
    isFtBook() { return !!(this.currentBook && this.currentBook.is_foreign_trade); },
    tradeModeLabel() { return { FOB: 'FOB', CIF: 'CIF', CFR: 'CFR' }; },
    kindLabel() { return { receipt: '收汇', verification: '待核查', settlement: '结汇' }; },
    refundStatusLabel() {
      return { collecting: '资料收集中', submitted: '已申报', approved: '已审批', received: '已到账' };
    },
    refundStatusColor() {
      return { collecting: 'info', submitted: 'warning', approved: 'primary', received: 'success' };
    },
  },
  mounted() { this.load(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    async load() {
      this.loading = true;
      try {
        this.summary = await ZCAPI.ft.summary();
        await Promise.all([this.loadDecls(), this.loadReceipts(), this.loadRefunds(), this.loadPlatform()]);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      }
      this.loading = false;
    },
    async loadDecls() {
      const r = await ZCAPI.ft.decls({ keyword: this.declKeyword || null });
      this.decls = r.items || [];
    },
    async loadReceipts() {
      const r = await ZCAPI.ft.receipts({ kind: this.receiptKind || null });
      this.receipts = r.items || [];
    },
    async loadRefunds() {
      const r = await ZCAPI.ft.refunds({ status: this.refundStatus || null });
      this.refunds = r.items || [];
    },
    async loadPlatform() {
      this.platform = await ZCAPI.ft.platform();
      this.platformNotes = this.platform.notes || '';
    },
    openLink(url) { window.open(url, '_blank', 'noopener'); },

    // ---------- 报关单 ----------
    openNewDecl() {
      if (!this.requireFtBook()) return;
      this.declForm = {
        book_id: this.currentBookId, decl_no: '', export_date: '', trade_mode: 'FOB',
        currency: 'USD', fx_rate: '1', usd_amount: '', customer_abroad: '',
        goods_count: 0, remark: '',
        lines: [{ hs_code: '', goods_name: '', qty: '', unit: '', unit_price: '', amount: '' }],
      };
      this.declDialog = true;
    },
    requireFtBook() {
      if (!this.currentBookId) {
        ElementPlus.ElMessage.warning('请先在右上角切换到具体客户账套');
        return false;
      }
      if (!this.isFtBook) {
        ElementPlus.ElMessage.warning('该客户不是外贸客户，请在客户档案勾选外贸标记');
        return false;
      }
      return true;
    },
    addDeclLine() {
      this.declForm.lines.push({ hs_code: '', goods_name: '', qty: '', unit: '', unit_price: '', amount: '' });
    },
    async submitDecl() {
      const f = this.declForm;
      if (!f.decl_no || !f.export_date || !f.usd_amount) {
        return ElementPlus.ElMessage.warning('请填写报关单号 / 出口日期 / 外币金额');
      }
      this.declSubmitting = true;
      try {
        await ZCAPI.ft.createDecl(f);
        ElementPlus.ElMessage.success('报关单已登记');
        this.declDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.declSubmitting = false;
    },
    async openDecl(d) {
      try {
        this.detail = await ZCAPI.ft.decl(d.id);
        this.detailDialog = true;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载详情失败');
      }
    },
    async removeDecl(d) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '确认删除报关单 ' + d.decl_no + '？（商品行一并归档）', '删除报关单',
          { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.ft.removeDecl(d.id);
        ElementPlus.ElMessage.success('已删除');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },
    // CSV 导入
    openImport() {
      if (!this.requireFtBook()) return;
      this.importFile = null;
      this.importRows = null;
      this.importDialog = true;
    },
    onImportFile(ev) {
      const file = ev.target.files && ev.target.files[0];
      if (!file) { this.importRows = null; return; }
      const reader = new FileReader();
      reader.onload = () => { this.parseCsv(String(reader.result || '')); };
      reader.onerror = () => { this.importRows = null; };
      reader.readAsText(file, 'utf-8');
      this.importFile = file;
    },
    parseCsv(text) {
      // 简易 CSV 解析（支持引号包裹的逗号）
      const rows = [];
      let row = [], cell = '', inQ = false;
      for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (inQ) {
          if (c === '"') {
            if (text[i + 1] === '"') { cell += '"'; i++; }
            else inQ = false;
          } else cell += c;
        } else if (c === '"') inQ = true;
        else if (c === ',') { row.push(cell); cell = ''; }
        else if (c === '\n' || c === '\r') {
          if (c === '\r' && text[i + 1] === '\n') i++;
          row.push(cell); cell = '';
          if (row.some((x) => x.trim())) rows.push(row);
          row = [];
        } else cell += c;
      }
      row.push(cell);
      if (row.some((x) => x.trim())) rows.push(row);
      this.importRows = rows;
    },
    async doImport() {
      if (!this.importRows || this.importRows.length < 2) {
        return ElementPlus.ElMessage.warning('未解析到有效数据行');
      }
      this.importing = true;
      try {
        const r = await ZCAPI.ft.importDecls(this.currentBookId, this.importRows);
        let msg = '新增 ' + r.created + ' 条，跳过 ' + r.skipped + ' 条';
        if (r.errors && r.errors.length) msg += '，失败 ' + r.errors.length + ' 条';
        ElementPlus.ElMessage[r.errors && r.errors.length ? 'warning' : 'success'](msg);
        this.importDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '导入失败');
      }
      this.importing = false;
    },

    // ---------- 收汇 ----------
    openNewReceipt() {
      if (!this.requireFtBook()) return;
      this.receiptForm = {
        book_id: this.currentBookId, decl_id: null, receipt_date: '', currency: 'USD',
        amount: '', fx_rate: '1', kind: 'receipt', bank_fee: '0', remark: '',
      };
      this.receiptDialog = true;
    },
    async submitReceipt() {
      const f = this.receiptForm;
      if (!f.receipt_date || !f.amount) {
        return ElementPlus.ElMessage.warning('请填写收汇日期和金额');
      }
      try {
        await ZCAPI.ft.createReceipt(f);
        ElementPlus.ElMessage.success('收汇已登记');
        this.receiptDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
    },
    async removeReceipt(r) {
      try {
        await ElementPlus.ElMessageBox.confirm('确认删除该收汇记录？', '删除收汇',
          { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.ft.removeReceipt(r.id);
        ElementPlus.ElMessage.success('已删除');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },

    // ---------- 退税 ----------
    openNewRefund() {
      if (!this.requireFtBook()) return;
      if (!this.decls.length) {
        return ElementPlus.ElMessage.warning('请先登记报关单，退税需关联报关单');
      }
      this.refundForm = {
        book_id: this.currentBookId, decl_id: null, period: '', kind: '免抵退',
        status: 'collecting', refund_amount: '', received_date: '', remark: '',
      };
      this.refundDialog = true;
    },
    async submitRefund() {
      const f = this.refundForm;
      if (!f.decl_id || !f.period || !f.refund_amount) {
        return ElementPlus.ElMessage.warning('请填写报关单 / 属期 / 应退税额');
      }
      try {
        await ZCAPI.ft.createRefund(f);
        ElementPlus.ElMessage.success('退税记录已登记');
        this.refundDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
    },
    async advanceRefund(r) {
      const flow = ['collecting', 'submitted', 'approved', 'received'];
      const idx = flow.indexOf(r.status);
      if (idx < 0 || idx >= flow.length - 1) return;
      const next = flow[idx + 1];
      let receivedDate = null;
      if (next === 'received') {
        try {
          const { value } = await ElementPlus.ElMessageBox.prompt('请输入退税到账日期', '退税到账', {
            inputValue: new Date().toISOString().slice(0, 10),
            inputPattern: /^\d{4}-\d{2}-\d{2}$/, inputErrorMessage: '格式 YYYY-MM-DD',
          });
          receivedDate = value;
        } catch (e) { return; }
      }
      try {
        await ZCAPI.ft.setRefundStatus(r.id, next, receivedDate);
        ElementPlus.ElMessage.success('已流转到【' + this.refundStatusLabel[next] + '】');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },

    // ---------- 平台备注 ----------
    async saveNotes() {
      this.notesSaving = true;
      try {
        await ZCAPI.ft.savePlatformNotes(this.platformNotes);
        ElementPlus.ElMessage.success('备注已保存');
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.notesSaving = false;
    },
  },
  template: `
  <div v-loading="loading">
    <!-- 汇总卡片 -->
    <div class="view-card" style="margin-bottom:12px" v-if="summary">
      <div class="stat-grid">
        <div class="stat-item">
          <div class="stat-label">报关单</div>
          <div class="stat-value">{{ summary.decl_count }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">报关总额（¥）</div>
          <div class="stat-value">{{ fmt(summary.total_cny) }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">已收汇（¥）</div>
          <div class="stat-value" style="color:var(--zc-success,#67C23A)">{{ fmt(summary.received_cny) }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">未收汇差额（¥）</div>
          <div class="stat-value" style="color:var(--zc-warn,#E6A23C)">{{ fmt(summary.unreceived_cny) }}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">退税在途</div>
          <div class="stat-value">{{ summary.refund_pending_count }} 笔 / ¥{{ fmt(summary.refund_pending_amount) }}</div>
        </div>
      </div>
    </div>

    <div class="view-card">
      <el-tabs v-model="tab">
        <!-- 报关单 -->
        <el-tab-pane label="报关单台账" name="decls">
          <div class="form-head" style="margin-bottom:10px">
            <el-input v-model="declKeyword" placeholder="搜报关单号 / 境外客户" clearable
                      style="width:240px" size="small" @clear="loadDecls()"
                      @keyup.enter="loadDecls()"></el-input>
            <div style="flex:1"></div>
            <el-button size="small" @click="openImport">
              <el-icon><upload></upload></el-icon> CSV 导入
            </el-button>
            <el-button size="small" type="primary" @click="openNewDecl">
              <el-icon><plus></plus></el-icon> 登记报关单
            </el-button>
          </div>
          <el-table :data="decls" size="small" border stripe @row-click="openDecl"
                    style="cursor:pointer">
            <el-table-column prop="decl_no" label="报关单号" min-width="150"></el-table-column>
            <el-table-column prop="book_name" label="客户" width="110"></el-table-column>
            <el-table-column prop="export_date" label="出口日期" width="100"></el-table-column>
            <el-table-column prop="trade_mode" label="成交方式" width="80"></el-table-column>
            <el-table-column prop="currency" label="币种" width="60"></el-table-column>
            <el-table-column prop="usd_amount" label="外币金额" width="110" align="right">
              <template #default="{row}">{{ fmt(row.usd_amount) }}</template>
            </el-table-column>
            <el-table-column prop="cny_total" label="人民币总额" width="110" align="right">
              <template #default="{row}">{{ fmt(row.cny_total) }}</template>
            </el-table-column>
            <el-table-column label="已收汇" width="100" align="right">
              <template #default="{row}">{{ fmt(row.received_amount) }}</template>
            </el-table-column>
            <el-table-column label="未收差额" width="100" align="right">
              <template #default="{row}">
                <span :style="{color: parseFloat(row.unreceived) > 0 ? 'var(--el-color-warning)' : 'var(--el-color-success)'}">
                  {{ fmt(row.unreceived) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="customer_abroad" label="境外客户" min-width="130" show-overflow-tooltip></el-table-column>
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{row}">
                <el-button link type="danger" size="small" @click.stop="removeDecl(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 收汇 -->
        <el-tab-pane label="收汇结汇" name="receipts">
          <div class="form-head" style="margin-bottom:10px">
            <el-select v-model="receiptKind" placeholder="全部类型" clearable size="small"
                       style="width:140px" @change="loadReceipts">
              <el-option label="收汇" value="receipt"></el-option>
              <el-option label="待核查" value="verification"></el-option>
              <el-option label="结汇" value="settlement"></el-option>
            </el-select>
            <div style="flex:1"></div>
            <el-button size="small" type="primary" @click="openNewReceipt">
              <el-icon><plus></plus></el-icon> 登记收汇
            </el-button>
          </div>
          <el-table :data="receipts" size="small" border stripe>
            <el-table-column prop="receipt_date" label="收汇日期" width="100"></el-table-column>
            <el-table-column prop="book_name" label="客户" width="110"></el-table-column>
            <el-table-column prop="decl_no" label="关联报关单" min-width="150"></el-table-column>
            <el-table-column prop="currency" label="币种" width="60"></el-table-column>
            <el-table-column prop="amount" label="外币金额" width="110" align="right">
              <template #default="{row}">{{ fmt(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="fx_rate" label="汇率" width="80" align="right"></el-table-column>
            <el-table-column prop="cny_amount" label="人民币金额" width="110" align="right">
              <template #default="{row}">{{ fmt(row.cny_amount) }}</template>
            </el-table-column>
            <el-table-column label="类型" width="80">
              <template #default="{row}">
                <el-tag size="small" :type="row.kind === 'receipt' ? 'success' : (row.kind === 'settlement' ? 'primary' : 'warning')">
                  {{ kindLabel[row.kind] || row.kind }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="bank_fee" label="手续费" width="80" align="right">
              <template #default="{row}">{{ fmt(row.bank_fee) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{row}">
                <el-button link type="danger" size="small" @click="removeReceipt(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 退税 -->
        <el-tab-pane label="出口退税" name="refunds">
          <div class="form-head" style="margin-bottom:10px">
            <el-select v-model="refundStatus" placeholder="全部状态" clearable size="small"
                       style="width:140px" @change="loadRefunds">
              <el-option v-for="(label, s) in refundStatusLabel" :key="s" :label="label" :value="s"></el-option>
            </el-select>
            <div style="flex:1"></div>
            <el-button size="small" type="primary" @click="openNewRefund">
              <el-icon><plus></plus></el-icon> 登记退税
            </el-button>
          </div>
          <el-table :data="refunds" size="small" border stripe>
            <el-table-column prop="period" label="属期" width="80"></el-table-column>
            <el-table-column prop="book_name" label="客户" width="110"></el-table-column>
            <el-table-column prop="decl_no" label="关联报关单" min-width="150"></el-table-column>
            <el-table-column prop="kind" label="方式" width="80"></el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{row}">
                <el-tag size="small" :type="refundStatusColor[row.status] || 'info'">
                  {{ refundStatusLabel[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="refund_amount" label="应退税额" width="110" align="right">
              <template #default="{row}">{{ fmt(row.refund_amount) }}</template>
            </el-table-column>
            <el-table-column prop="received_date" label="到账日期" width="100"></el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{row}">
                <el-button v-if="row.status !== 'received'" link type="primary" size="small"
                           @click="advanceRefund(row)">流转</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 平台链接 -->
        <el-tab-pane label="平台链接" name="platform">
          <div v-if="platform" style="max-width:760px">
            <div class="link-grid">
              <div class="link-card" v-for="(p, key) in platform.links" :key="key"
                   @click="openLink(p.url)">
                <div style="font-size:15px; font-weight:600; margin-bottom:6px">{{ p.name }}</div>
                <div style="font-size:12px; color:var(--zc-text-2); word-break:break-all">{{ p.url }}</div>
                <div style="font-size:12px; color:var(--zc-primary); margin-top:8px">
                  点击前往 ↗
                </div>
              </div>
            </div>
            <div style="margin-top:16px">
              <div style="font-size:13px; font-weight:600; margin-bottom:8px">
                操作备注（账号注意事项 / 操作要点，仅本机保存）
              </div>
              <el-input v-model="platformNotes" type="textarea" :rows="5"
                        placeholder="例如：单一窗口用法人卡登录，报关单导出路径：…"></el-input>
              <el-button size="small" type="primary" style="margin-top:8px"
                         :loading="notesSaving" @click="saveNotes">保存备注</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 新建报关单 -->
    <el-dialog v-model="declDialog" title="登记报关单" width="720px" top="6vh">
      <el-form v-if="declForm" label-position="top" size="small">
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="报关单号" required>
              <el-input v-model="declForm.decl_no" placeholder="18 位海关编号"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="出口日期" required>
              <el-date-picker v-model="declForm.export_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="成交方式">
              <el-select v-model="declForm.trade_mode" style="width:100%">
                <el-option label="FOB 离岸价" value="FOB"></el-option>
                <el-option label="CIF 到岸价" value="CIF"></el-option>
                <el-option label="CFR 成本加运费" value="CFR"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="币种">
              <el-input v-model="declForm.currency"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="汇率">
              <el-input v-model="declForm.fx_rate"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="外币金额" required>
              <el-input v-model="declForm.usd_amount"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="件数">
              <el-input v-model="declForm.goods_count" type="number"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="境外客户">
          <el-input v-model="declForm.customer_abroad"></el-input>
        </el-form-item>

        <div style="font-size:13px; font-weight:600; margin:6px 0">商品行（可留空，填了自动汇总总额）</div>
        <div v-for="(ln, i) in declForm.lines" :key="i" style="display:flex; gap:6px; margin-bottom:6px">
          <el-input v-model="ln.hs_code" placeholder="HS编码" style="width:110px"></el-input>
          <el-input v-model="ln.goods_name" placeholder="品名" style="flex:1"></el-input>
          <el-input v-model="ln.qty" placeholder="数量" style="width:80px"></el-input>
          <el-input v-model="ln.unit" placeholder="单位" style="width:70px"></el-input>
          <el-input v-model="ln.unit_price" placeholder="单价" style="width:90px"></el-input>
          <el-input v-model="ln.amount" placeholder="金额" style="width:100px"></el-input>
          <el-button link type="danger" @click="declForm.lines.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" @click="addDeclLine">+ 加一行</el-button>
      </el-form>
      <template #footer>
        <el-button @click="declDialog = false">取消</el-button>
        <el-button type="primary" :loading="declSubmitting" @click="submitDecl">保存</el-button>
      </template>
    </el-dialog>

    <!-- 报关单详情 -->
    <el-dialog v-model="detailDialog" :title="detail ? '报关单 ' + detail.decl.decl_no : ''"
               width="760px" top="6vh">
      <template v-if="detail">
        <div style="display:flex; gap:24px; margin-bottom:12px; font-size:13px">
          <span>客户：<b>{{ detail.decl.book_name }}</b></span>
          <span>出口日期：{{ detail.decl.export_date }}</span>
          <span>{{ detail.decl.trade_mode }} / {{ detail.decl.currency }}</span>
          <span>外币：{{ fmt(detail.decl.usd_amount) }}</span>
          <span>人民币：¥{{ fmt(detail.decl.cny_total) }}</span>
          <span>境外客户：{{ detail.decl.customer_abroad || '—' }}</span>
        </div>
        <div style="display:flex; gap:24px; margin-bottom:12px; font-size:13px">
          <span>已收汇：<b style="color:var(--el-color-success)">{{ fmt(detail.decl.received_amount) }}</b></span>
          <span>未收差额：<b style="color:var(--el-color-warning)">{{ fmt(detail.decl.unreceived) }}</b></span>
        </div>
        <div style="font-size:13px; font-weight:600; margin-bottom:6px">商品行</div>
        <el-table :data="detail.decl.lines || []" size="small" border style="margin-bottom:14px">
          <el-table-column prop="hs_code" label="HS编码" width="110"></el-table-column>
          <el-table-column prop="goods_name" label="品名" min-width="150"></el-table-column>
          <el-table-column prop="qty" label="数量" width="80" align="right"></el-table-column>
          <el-table-column prop="unit" label="单位" width="60"></el-table-column>
          <el-table-column prop="unit_price" label="单价" width="90" align="right"></el-table-column>
          <el-table-column prop="amount" label="金额" width="100" align="right"></el-table-column>
        </el-table>
        <div style="font-size:13px; font-weight:600; margin-bottom:6px">收汇记录</div>
        <el-table :data="detail.receipts" size="small" border style="margin-bottom:14px">
          <el-table-column prop="receipt_date" label="日期" width="100"></el-table-column>
          <el-table-column prop="amount" label="外币金额" width="110" align="right"></el-table-column>
          <el-table-column prop="cny_amount" label="人民币" width="110" align="right"></el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{row}">{{ kindLabel[row.kind] || row.kind }}</template>
          </el-table-column>
          <el-table-column prop="remark" label="备注" min-width="120"></el-table-column>
        </el-table>
        <div style="font-size:13px; font-weight:600; margin-bottom:6px">退税记录</div>
        <el-table :data="detail.refunds" size="small" border>
          <el-table-column prop="period" label="属期" width="80"></el-table-column>
          <el-table-column prop="kind" label="方式" width="80"></el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{row}">{{ refundStatusLabel[row.status] || row.status }}</template>
          </el-table-column>
          <el-table-column prop="refund_amount" label="应退税额" width="110" align="right"></el-table-column>
          <el-table-column prop="received_date" label="到账日期" width="100"></el-table-column>
        </el-table>
      </template>
    </el-dialog>

    <!-- 新建收汇 -->
    <el-dialog v-model="receiptDialog" title="登记收汇" width="520px">
      <el-form v-if="receiptForm" label-position="top" size="small">
        <el-form-item label="关联报关单（可空 = 预收款等）">
          <el-select v-model="receiptForm.decl_id" filterable clearable style="width:100%"
                     placeholder="选择报关单">
            <el-option v-for="d in decls.filter(x => x.book_id === receiptForm.book_id)"
                       :key="d.id" :value="d.id"
                       :label="d.decl_no + '（未收 ' + d.unreceived + '）'"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="收汇日期" required>
              <el-date-picker v-model="receiptForm.receipt_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类型">
              <el-select v-model="receiptForm.kind" style="width:100%">
                <el-option label="收汇" value="receipt"></el-option>
                <el-option label="待核查" value="verification"></el-option>
                <el-option label="结汇" value="settlement"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="币种">
              <el-input v-model="receiptForm.currency"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="外币金额" required>
              <el-input v-model="receiptForm.amount"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="汇率">
              <el-input v-model="receiptForm.fx_rate"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="银行手续费">
              <el-input v-model="receiptForm.bank_fee"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="receiptForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="receiptDialog = false">取消</el-button>
        <el-button type="primary" @click="submitReceipt">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新建退税 -->
    <el-dialog v-model="refundDialog" title="登记出口退税" width="520px">
      <el-form v-if="refundForm" label-position="top" size="small">
        <el-form-item label="关联报关单" required>
          <el-select v-model="refundForm.decl_id" filterable style="width:100%">
            <el-option v-for="d in decls.filter(x => x.book_id === refundForm.book_id)"
                       :key="d.id" :value="d.id" :label="d.decl_no"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="属期" required>
              <el-input v-model="refundForm.period" placeholder="如 2026-08"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="退税方式">
              <el-select v-model="refundForm.kind" style="width:100%">
                <el-option label="免抵退" value="免抵退"></el-option>
                <el-option label="免退" value="免退"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="应退税额" required>
              <el-input v-model="refundForm.refund_amount"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="refundForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="refundDialog = false">取消</el-button>
        <el-button type="primary" @click="submitRefund">保存</el-button>
      </template>
    </el-dialog>

    <!-- CSV 导入 -->
    <el-dialog v-model="importDialog" title="导入单一窗口报关明细 CSV" width="600px">
      <div style="font-size:13px; color:var(--zc-text-2); margin-bottom:10px">
        从「中国国际贸易单一窗口 → 综合查询 → 报关单查询」导出明细 CSV。
        系统按表头宽松匹配（报关单号/出口日期/总价等），报关单号已存在自动跳过。
      </div>
      <input type="file" accept=".csv,.txt" @change="onImportFile">
      <div v-if="importRows" style="margin-top:10px; font-size:13px">
        已解析 <b>{{ importRows.length - 1 }}</b> 行数据（含表头 {{
          importRows[0] && importRows[0].slice(0, 6).join(' | ')
        }}…）
      </div>
      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importRows" @click="doImport">
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
