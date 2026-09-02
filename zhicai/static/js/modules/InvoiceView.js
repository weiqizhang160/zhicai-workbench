// 发票管理（项目书 7.6）：进项/销项 Tab + Excel 导入向导 + 月末视图。
// 导入三步：上传文件 → 预览校验（错误行标红说明）→ 确认入库。
window.InvoiceView = Vue.defineComponent({
  name: 'InvoiceView',
  data() {
    const d = new Date();
    return {
      tab: 'output',           // output 销项 / input 进项
      period: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      kw: '',
      rows: [],
      loading: false,

      // 新增/编辑
      editDialog: false,
      editingId: null,
      form: this.blankForm(),

      // 导入向导
      importDialog: false,
      importStep: 0,           // 0 上传 / 1 预览
      importFile: null,
      importResult: null,
      importing: false,

      // 月末统计
      summary: null,
    };
  },
  computed: {
    monthOptions() {
      return Array.from({ length: 12 }, (_, i) => ({
        value: `${new Date().getFullYear()}-${String(i + 1).padStart(2, '0')}`,
        label: `${i + 1} 月`,
      }));
    },
    // 前端即时计算价税合计（后端也会用 Decimal 再算一次，保证精度）
    computedTotal() {
      const g = parseFloat(this.form.goods_amount) || 0;
      const r = parseFloat(this.form.tax_rate) || 0;
      const tax = Math.round(g * r * 100) / 100;
      return (Math.round((g + tax) * 100) / 100).toFixed(2);
    },
  },
  watch: {
    tab() { this.load(); },
    period() { this.load(); this.loadSummary(); },
  },
  mounted() { this.load(); this.loadSummary(); },
  methods: {
    blankForm() {
      return {
        direction: 'output', invoice_type: 'special', invoice_code: '',
        invoice_no: '', invoice_date: new Date().toISOString().slice(0, 10),
        partner_name: '', partner_tax_no: '',
        goods_amount: '', tax_rate: '0.13', tax_amount: '', category: 'office',
        remark: '',
      };
    },
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    stateTag(s) {
      return { registered: '已登记', entry_generated: '已生成凭证', voided: '已作废' }[s] || s;
    },
    stateType(s) {
      return { registered: 'info', entry_generated: 'success', voided: 'danger' }[s] || 'info';
    },
    catLabel(c) {
      return ({ office: '办公费', travel: '差旅费', rent: '房租', material: '材料采购',
                entertain: '业务招待', utility: '水电物业', telecom: '通讯网络',
                logistics: '运输物流', salary: '工资社保', other: '其他' })[c] || (c || '—');
    },

    async load() {
      this.loading = true;
      try {
        const r = await ZCAPI.inv.bills({ direction: this.tab, period: this.period,
                                          kw: this.kw, limit: 200 });
        this.rows = r.invoices || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
        this.rows = [];
      }
      this.loading = false;
    },
    async loadSummary() {
      try {
        this.summary = await ZCAPI.inv.monthSummary(this.period);
      } catch (e) { this.summary = null; }
    },

    // ---------- 新增 / 编辑 ----------
    openCreate() {
      this.editingId = null;
      this.form = this.blankForm();
      this.form.direction = this.tab;
      this.editDialog = true;
    },
    openEdit(row) {
      this.editingId = row.id;
      this.form = {
        direction: row.direction, invoice_type: row.invoice_type,
        invoice_code: row.invoice_code || '', invoice_no: row.invoice_no,
        invoice_date: row.invoice_date, partner_name: row.partner_name || '',
        partner_tax_no: row.partner_tax_no || '',
        goods_amount: row.goods_amount, tax_rate: row.tax_rate,
        tax_amount: row.tax_amount, category: row.category || 'office',
        remark: row.remark || '',
      };
      this.editDialog = true;
    },
    async saveInvoice() {
      if (!this.form.invoice_no.trim()) {
        return ElementPlus.ElMessage.warning('请填写发票号码');
      }
      if (!this.form.invoice_date) {
        return ElementPlus.ElMessage.warning('请选择开票日期');
      }
      try {
        if (this.editingId) {
          await ZCAPI.inv.update(this.editingId, this.form);
          ElementPlus.ElMessage.success('已保存');
        } else {
          await ZCAPI.inv.create(this.form);
          ElementPlus.ElMessage.success('已登记');
        }
        this.editDialog = false;
        this.load();
        this.loadSummary();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
    },
    async removeInvoice(row) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确认删除发票 ${row.invoice_no}？`, '删除确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        await ZCAPI.inv.remove(row.id);
        ElementPlus.ElMessage.success('已删除');
        this.load(); this.loadSummary();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },

    // ---------- 导入向导 ----------
    onPickFile(file) {
      this.importFile = file.raw;
      return false;
    },
    downloadTemplate() {
      location.href = '/api/v1/inv/template';
    },
    async doPreview() {
      if (!this.importFile) {
        return ElementPlus.ElMessage.warning('请先选择文件');
      }
      this.importing = true;
      try {
        this.importResult = await ZCAPI.inv.importPreview(this.importFile);
        this.importStep = 1;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '解析失败');
      }
      this.importing = false;
    },
    async doCommit() {
      if (!this.importResult || !this.importResult.preview.length) return;
      try {
        const r = await ZCAPI.inv.importCommit(this.importResult.preview);
        ElementPlus.ElMessage.success(`成功导入 ${r.imported} 张发票`);
        this.importDialog = false;
        this.resetImport();
        this.load();
        this.loadSummary();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '导入失败');
      }
    },
    resetImport() {
      this.importStep = 0;
      this.importFile = null;
      this.importResult = null;
    },
    openMove(id) { location.hash = '#/move/' + id; },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><ticket></ticket></el-icon>
          <div style="font-size:16px; font-weight:600">发票管理</div>
        </div>
        <div style="flex:1"></div>
        <el-button size="small" @click="downloadTemplate">下载导入模板</el-button>
        <el-button size="small" type="warning" @click="importDialog = true">
          <el-icon><upload></upload></el-icon> Excel 导入
        </el-button>
        <el-button size="small" type="primary" @click="openCreate">
          <el-icon><plus></plus></el-icon> 登记发票
        </el-button>
      </div>

      <!-- 月末视图 -->
      <div v-if="summary" class="ledger-total-line" style="margin-bottom:12px">
        {{ period }} 汇总：
        销项 <b>{{ summary.output.count }}</b> 张（不含税 {{ fmt(summary.output.goods) }}，
        税额 {{ fmt(summary.output.tax) }}）｜
        进项 <b>{{ summary.input.count }}</b> 张（不含税 {{ fmt(summary.input.goods) }}，
        税额 {{ fmt(summary.input.tax) }}）｜
        应纳税额 <b>{{ fmt(summary.vat_payable) }}</b>
        <span style="font-size:12px; color:var(--zc-text-2); margin-left:6px">
          （增值税申报底稿取数来源）
        </span>
      </div>

      <el-form :inline="true" size="small" style="margin: 12px 0">
        <el-form-item label="期间">
          <el-select v-model="period" style="width:110px">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-input v-model="kw" placeholder="号码/单位/代码" clearable
                    style="width:220px" @keyup.enter="load"></el-input>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load">查询</el-button>
        </el-form-item>
      </el-form>

      <el-tabs v-model="tab">
        <el-tab-pane label="销项发票（开出）" name="output"></el-tab-pane>
        <el-tab-pane label="进项发票（收到）" name="input"></el-tab-pane>
      </el-tabs>

      <el-table :data="rows" border size="small" v-loading="loading" height="440">
        <el-table-column prop="invoice_date" label="开票日期" width="110"></el-table-column>
        <el-table-column prop="invoice_no" label="发票号码" width="130"></el-table-column>
        <el-table-column prop="partner_name" label="对方单位" min-width="180"></el-table-column>
        <el-table-column label="不含税" width="120" align="right">
          <template #default="{ row }">{{ fmt(row.goods_amount) }}</template>
        </el-table-column>
        <el-table-column label="税额" width="110" align="right">
          <template #default="{ row }">{{ fmt(row.tax_amount) }}</template>
        </el-table-column>
        <el-table-column label="价税合计" width="130" align="right">
          <template #default="{ row }"><b>{{ fmt(row.total_amount) }}</b></template>
        </el-table-column>
        <el-table-column label="税率" width="70" align="center">
          <template #default="{ row }">{{ (parseFloat(row.tax_rate) * 100).toFixed(0) }}%</template>
        </el-table-column>
        <el-table-column label="类别" width="100">
          <template #default="{ row }">{{ catLabel(row.category) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="stateType(row.state)">{{ stateTag(row.state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭证" width="90">
          <template #default="{ row }">
            <el-link v-if="row.move_id" type="primary" @click="openMove(row.move_id)">#{{ row.move_id }}</el-link>
            <span v-else style="color:var(--zc-text-3)">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="removeInvoice(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 登记/编辑发票 -->
    <el-dialog v-model="editDialog" :title="editingId ? '编辑发票' : '登记发票'" width="620px">
      <el-form label-position="top" size="small">
        <div class="form-grid">
          <el-form-item label="方向">
            <el-select v-model="form.direction" style="width:100%">
              <el-option label="销项（开出）" value="output"></el-option>
              <el-option label="进项（收到）" value="input"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="票种">
            <el-select v-model="form.invoice_type" style="width:100%">
              <el-option label="专用发票" value="special"></el-option>
              <el-option label="普通发票" value="normal"></el-option>
              <el-option label="数电票" value="electronic"></el-option>
              <el-option label="其他" value="other"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="发票代码">
            <el-input v-model="form.invoice_code"></el-input>
          </el-form-item>
          <el-form-item label="发票号码" required>
            <el-input v-model="form.invoice_no"></el-input>
          </el-form-item>
          <el-form-item label="开票日期" required>
            <el-date-picker v-model="form.invoice_date" type="date" value-format="YYYY-MM-DD"
                            style="width:100%"></el-date-picker>
          </el-form-item>
          <el-form-item label="对方单位">
            <el-input v-model="form.partner_name"></el-input>
          </el-form-item>
          <el-form-item label="不含税金额" required>
            <el-input v-model="form.goods_amount" placeholder="0.00"></el-input>
          </el-form-item>
          <el-form-item label="税率">
            <el-select v-model="form.tax_rate" style="width:100%">
              <el-option label="13%" value="0.13"></el-option>
              <el-option label="9%" value="0.09"></el-option>
              <el-option label="6%" value="0.06"></el-option>
              <el-option label="3%" value="0.03"></el-option>
              <el-option label="1%" value="0.01"></el-option>
              <el-option label="0%" value="0"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="费用类别（进项自动记账用）">
            <el-select v-model="form.category" style="width:100%">
              <el-option v-for="c in [['office','办公费'],['travel','差旅费'],['rent','房租'],['material','材料采购'],['entertain','业务招待'],['utility','水电物业'],['telecom','通讯网络'],['logistics','运输物流'],['salary','工资社保'],['other','其他']]"
                         :key="c[0]" :label="c[1]" :value="c[0]"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="价税合计（自动计算）">
            <el-input :model-value="computedTotal" readonly></el-input>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="saveInvoice">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入向导 -->
    <el-dialog v-model="importDialog" title="Excel 批量导入发票" width="820px"
               @closed="resetImport">
      <el-steps :active="importStep" finish-status="success" align-center style="margin-bottom:18px">
        <el-step title="选择文件"></el-step>
        <el-step title="预览校验"></el-step>
      </el-steps>

      <!-- 第一步：上传 -->
      <div v-if="importStep === 0">
        <el-upload :auto-upload="false" :on-change="onPickFile" :limit="1"
                   accept=".csv,.xlsx,.xls,.txt">
          <el-button type="primary">选择文件</el-button>
        </el-upload>
        <div style="margin-top:14px; font-size:13px; color:var(--zc-text-2); line-height:1.9">
          支持 CSV / Excel（.xlsx）。<br>
          表头需包含：方向、发票号码、开票日期、不含税金额，其余列可选。<br>
          不确定格式可先
          <el-link type="primary" @click="downloadTemplate">下载标准模板</el-link>
          对照填写。编码自动识别（UTF-8 / GBK）。
        </div>
      </div>

      <!-- 第二步：预览 -->
      <div v-else-if="importResult">
        <div class="ledger-total-line" style="margin-bottom:12px">
          共解析 <b>{{ importResult.total }}</b> 行，
          可导入 <b style="color:var(--zc-success)">{{ importResult.valid }}</b> 行，
          <b style="color:var(--zc-danger)">{{ importResult.invalid }}</b> 行有问题
          <span v-if="importResult.invalid" style="margin-left:8px; font-size:12px">
            （错误行不会导入，修正后可重新上传）
          </span>
        </div>

        <div style="font-size:13px; font-weight:600; margin:10px 0 6px">可导入预览</div>
        <el-table :data="importResult.preview" border size="small" height="220">
          <el-table-column prop="invoice_date" label="日期" width="110"></el-table-column>
          <el-table-column prop="invoice_no" label="号码" width="120"></el-table-column>
          <el-table-column prop="partner_name" label="对方单位" min-width="150"></el-table-column>
          <el-table-column prop="goods_amount" label="不含税" width="100" align="right"></el-table-column>
          <el-table-column prop="tax_amount" label="税额" width="90" align="right"></el-table-column>
          <el-table-column prop="total_amount" label="价税合计" width="110" align="right"></el-table-column>
          <el-table-column label="方向" width="70">
            <template #default="{ row }">{{ row.direction === 'output' ? '销项' : '进项' }}</template>
          </el-table-column>
        </el-table>

        <div v-if="importResult.invalid" style="font-size:13px; font-weight:600; margin:12px 0 6px">
          <span style="color:var(--zc-danger)">错误行（{{ importResult.invalid }}）</span>
        </div>
        <el-table v-if="importResult.invalid" :data="importResult.errors" border size="small"
                  height="180" :row-class-name="() => 'import-error-row'">
          <el-table-column prop="row" label="行号" width="70"></el-table-column>
          <el-table-column prop="message" label="问题说明" min-width="260"></el-table-column>
          <el-table-column label="原数据" min-width="220">
            <template #default="{ row }">
              <span style="font-size:12px; color:var(--zc-text-2)">
                {{ (row.data.invoice_no || '') + ' / ' + (row.data.invoice_date || '') }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button v-if="importStep === 0" type="primary" :loading="importing" @click="doPreview">
          下一步：预览校验
        </el-button>
        <template v-else>
          <el-button @click="importStep = 0">上一步</el-button>
          <el-button type="success" :disabled="!importResult || !importResult.valid"
                     @click="doCommit">
            确认导入（{{ importResult ? importResult.valid : 0 }} 行）
          </el-button>
        </template>
      </template>
    </el-dialog>
  </div>
  `,
});
