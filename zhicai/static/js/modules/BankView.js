// 银行对账工作台（项目书 7.8）：左流水列表 / 右凭证预生成区（可改科目）
// + 流水导入（编码容错）+ 按月对账汇总（期初 + 收入 - 支出 = 期末）。
window.BankView = Vue.defineComponent({
  name: 'BankView',
  data() {
    const d = new Date();
    return {
      period: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      lines: [],
      loading: false,
      stateFilter: '',
      current: null,        // 选中的流水
      preview: null,        // 凭证预览（可改）
      previewLoading: false,
      generating: false,
      summary: null,

      // 导入
      importDialog: false,
      importStep: 0,
      importFile: null,
      importResult: null,
      importing: false,
      bankAlias: '',
      accountNo: '',
    };
  },
  computed: {
    monthOptions() {
      const y = new Date().getFullYear();
      return Array.from({ length: 12 }, (_, i) => ({
        value: `${y}-${String(i + 1).padStart(2, '0')}`, label: `${i + 1} 月`,
      }));
    },
    previewDebit() {
      if (!this.preview || !this.preview.lines) return '0.00';
      return this.sum(this.preview.lines.filter((l) => l.side === 'debit')
        .map((l) => l.debit));
    },
    previewCredit() {
      if (!this.preview || !this.preview.lines) return '0.00';
      return this.sum(this.preview.lines.filter((l) => l.side === 'credit')
        .map((l) => l.credit));
    },
    previewBalanced() {
      const d = parseFloat(this.previewDebit.replace(/,/g, '')) || 0;
      const c = parseFloat(this.previewCredit.replace(/,/g, '')) || 0;
      return Math.abs(d - c) < 0.005;
    },
  },
  mounted() { this.load(); this.loadSummary(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    sum(list) {
      const t = list.reduce((s, v) => s + (parseFloat(v) || 0), 0);
      return this.fmt(t);
    },
    amtOf(l) {
      return this.fmt(parseFloat(l.debit) > 0 ? l.debit : l.credit);
    },
    directionOf(l) {
      return parseFloat(l.debit) > 0 ? '收' : '付';
    },

    async load() {
      this.loading = true;
      try {
        const r = await ZCAPI.bank.lines({ period: this.period, state: this.stateFilter,
                                           limit: 500 });
        this.lines = r.lines || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
        this.lines = [];
      }
      this.loading = false;
      this.current = null;
      this.preview = null;
    },
    async loadSummary() {
      try {
        this.summary = await ZCAPI.bank.monthSummary(this.period);
      } catch (e) { this.summary = null; }
    },

    async selectLine(row) {
      this.current = row;
      this.preview = null;
      if (row.state === 'reconciled') return;   // 已对账的不显示预生成区
      this.previewLoading = true;
      try {
        const r = await ZCAPI.bank.linePreview(row.id);
        this.preview = r.preview;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '预览失败');
      }
      this.previewLoading = false;
    },

    async generate() {
      if (!this.current || !this.preview || !this.preview.lines.length) return;
      if (!this.previewBalanced) {
        return ElementPlus.ElMessage.error('借贷不平衡，不能生成凭证');
      }
      this.generating = true;
      try {
        const r = await ZCAPI.bank.generateMove(this.current.id, {
          rule_id: this.preview.rule_id,
          lines: this.preview.lines.map((l) => ({
            side: l.side, account_id: l.account_id, summary: l.summary,
            debit: l.debit, credit: l.credit,
          })),
        });
        ElementPlus.ElMessage.success(`已生成凭证 #${r.move_id}，流水已标记对账`);
        this.load();
        this.loadSummary();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '生成失败');
      }
      this.generating = false;
    },

    // ---------- 导入 ----------
    onPickFile(file) {
      this.importFile = file.raw;
      return false;
    },
    downloadTemplate() { location.href = '/api/v1/bank/template'; },
    async doPreview() {
      if (!this.importFile) return ElementPlus.ElMessage.warning('请先选择文件');
      this.importing = true;
      try {
        this.importResult = await ZCAPI.bank.importPreview(this.importFile, this.bankAlias,
                                                           this.accountNo);
        this.importStep = 1;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '解析失败');
      }
      this.importing = false;
    },
    async doCommit() {
      if (!this.importResult || !this.importResult.preview.length) return;
      try {
        const r = await ZCAPI.bank.importCommit(this.importResult.preview,
                                                this.bankAlias, this.accountNo);
        ElementPlus.ElMessage.success(`成功导入 ${r.imported} 条流水`);
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
          <el-icon style="font-size:22px; color:var(--zc-primary)"><bank-card></bank-card></el-icon>
          <div style="font-size:16px; font-weight:600">银行对账工作台</div>
        </div>
        <div style="flex:1"></div>
        <el-button size="small" @click="downloadTemplate">下载模板</el-button>
        <el-button size="small" type="warning" @click="importDialog = true">
          <el-icon><upload></upload></el-icon> 导入流水
        </el-button>
      </div>

      <el-form :inline="true" size="small" style="margin: 12px 0">
        <el-form-item label="期间">
          <el-select v-model="period" style="width:110px">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="stateFilter" clearable style="width:120px" placeholder="全部">
            <el-option label="未对账" value="unreconciled"></el-option>
            <el-option label="已对账" value="reconciled"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="load(); loadSummary()">查询</el-button>
        </el-form-item>
      </el-form>

      <!-- 月度对账汇总 -->
      <div v-if="summary" class="ledger-total-line" style="margin-bottom:12px">
        {{ period }} 对账汇总：期初 <b>{{ fmt(summary.opening) }}</b>
        ＋ 收入 <b>{{ fmt(summary.debit) }}</b>
        － 支出 <b>{{ fmt(summary.credit) }}</b>
        ＝ 期末 <b>{{ fmt(summary.closing) }}</b>
        <el-tag size="small" style="margin-left:10px">
          已对账 {{ summary.reconciled }} / 未对账 {{ summary.unreconciled }}
        </el-tag>
        <span style="font-size:12px; color:var(--zc-text-2); margin-left:8px">
          期末余额应与银行对账单核对一致
        </span>
      </div>

      <!-- 左右分栏 -->
      <div class="bank-split">
        <!-- 左：流水列表 -->
        <div class="bank-left">
          <div style="font-size:13px; font-weight:600; margin-bottom:6px">
            流水列表（未对账优先）
          </div>
          <el-table :data="lines" border size="small" height="430" v-loading="loading"
                    highlight-current-row @current-change="selectLine"
                    :row-class-name="({row}) => row.state === 'reconciled' ? 'bank-done-row' : ''">
            <el-table-column prop="trade_date" label="日期" width="104"></el-table-column>
            <el-table-column label="摘要" min-width="130">
              <template #default="{ row }">
                <div>{{ row.summary || row.counterpart_name || '—' }}</div>
                <div style="font-size:12px; color:var(--zc-text-2)">{{ row.counterpart_name }}</div>
              </template>
            </el-table-column>
            <el-table-column label="收支" width="60" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="parseFloat(row.debit) > 0 ? 'success' : 'warning'">
                  {{ directionOf(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="金额" width="110" align="right">
              <template #default="{ row }">{{ amtOf(row) }}</template>
            </el-table-column>
            <el-table-column label="余额" width="110" align="right">
              <template #default="{ row }">{{ row.balance ? fmt(row.balance) : '—' }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.state === 'reconciled' ? 'success' : 'info'">
                  {{ row.state === 'reconciled' ? '已对账' : '未对账' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 右：凭证预生成区 -->
        <div class="bank-right">
          <div style="font-size:13px; font-weight:600; margin-bottom:6px">凭证预生成</div>
          <div v-if="!current" class="bank-empty">
            点击左侧流水，查看自动带出的凭证
          </div>
          <div v-else-if="current.state === 'reconciled'" class="bank-empty">
            该流水已对账
            <div style="margin-top:8px">
              <el-link v-if="current.move_id" type="primary" @click="openMove(current.move_id)">
                查看凭证 #{{ current.move_id }}
              </el-link>
            </div>
          </div>
          <div v-else-if="previewLoading" class="bank-empty">匹配规则中…</div>
          <div v-else-if="!preview || !preview.lines.length" class="bank-empty">
            <el-icon style="font-size:20px; color:var(--zc-warning)"><warning-filled></warning-filled></el-icon>
            <div style="margin-top:6px">{{ (preview && preview.error) || '未匹配到规则' }}</div>
            <div style="font-size:12px; color:var(--zc-text-2); margin-top:4px">
              可到「记账规则」新增规则，或手工录入凭证
            </div>
          </div>
          <div v-else>
            <div class="ledger-total-line" style="margin-bottom:10px; font-size:12px">
              命中规则：<b>{{ preview.rule_name }}</b>
            </div>
            <el-table :data="preview.lines" border size="small">
              <el-table-column label="方向" width="56" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.side === 'debit' ? '' : 'success'">
                    {{ row.side === 'debit' ? '借' : '贷' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="account_code" label="科目" width="100"></el-table-column>
              <el-table-column prop="account_name" label="科目名称" min-width="120"></el-table-column>
              <el-table-column label="摘要" min-width="130">
                <template #default="{ row }">
                  <el-input v-model="row.summary" size="small"></el-input>
                </template>
              </el-table-column>
              <el-table-column label="金额" width="120" align="right">
                <template #default="{ row }">
                  <!-- v-model 只能绑定可赋值路径，不能写三元表达式（会触发 Vue 编译错误 42），
                       因此按借贷方向分别绑定 debit / credit -->
                  <el-input v-if="row.side === 'debit'" v-model="row.debit"
                            size="small" style="text-align:right"></el-input>
                  <el-input v-else v-model="row.credit"
                            size="small" style="text-align:right"></el-input>
                </template>
              </el-table-column>
            </el-table>
            <div class="ledger-total-line" style="margin-top:10px">
              合计 借 <b>{{ previewDebit }}</b> ／ 贷 <b>{{ previewCredit }}</b>
              <el-tag size="small" :type="previewBalanced ? 'success' : 'danger'" style="margin-left:8px">
                {{ previewBalanced ? '平衡' : '不平衡' }}
              </el-tag>
            </div>
            <div style="margin-top:12px">
              <el-button type="primary" :loading="generating" :disabled="!previewBalanced"
                         @click="generate">
                生成凭证并标记已对账
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 导入流水 -->
    <el-dialog v-model="importDialog" title="导入银行流水" width="820px" @closed="resetImport">
      <el-steps :active="importStep" finish-status="success" align-center style="margin-bottom:18px">
        <el-step title="选择文件"></el-step>
        <el-step title="预览校验"></el-step>
      </el-steps>

      <div v-if="importStep === 0">
        <el-form :inline="true" size="small" style="margin-bottom:12px">
          <el-form-item label="银行">
            <el-input v-model="bankAlias" placeholder="如 工行" style="width:120px"></el-input>
          </el-form-item>
          <el-form-item label="账号">
            <el-input v-model="accountNo" placeholder="选填" style="width:180px"></el-input>
          </el-form-item>
        </el-form>
        <el-upload :auto-upload="false" :on-change="onPickFile" :limit="1"
                   accept=".csv,.xlsx,.xls,.txt">
          <el-button type="primary">选择对账单文件</el-button>
        </el-upload>
        <div style="margin-top:14px; font-size:13px; color:var(--zc-text-2); line-height:1.9">
          支持 CSV / Excel，<b>编码自动识别</b>（UTF-8 / GBK，防表头乱码）。<br>
          表头需包含「交易日期」与「收入/支出金额」列；各行叫法不同（如「贷方发生额」= 收入）
          已内置常见别名，可到「参数配置」维护 bank.import.field_map 增加。<br>
          不确定就先 <el-link type="primary" @click="downloadTemplate">下载模板</el-link> 对照。
        </div>
      </div>

      <div v-else-if="importResult">
        <div class="ledger-total-line" style="margin-bottom:12px">
          识别编码 <b>{{ importResult.encoding }}</b>，
          可导入 <b style="color:var(--zc-success)">{{ importResult.valid }}</b> 条，
          <b style="color:var(--zc-danger)">{{ importResult.invalid }}</b> 条有问题
        </div>
        <el-table :data="importResult.preview" border size="small" height="280">
          <el-table-column prop="trade_date" label="日期" width="110"></el-table-column>
          <el-table-column prop="summary" label="摘要" min-width="140"></el-table-column>
          <el-table-column prop="counterpart_name" label="对方户名" min-width="150"></el-table-column>
          <el-table-column prop="debit" label="收入" width="110" align="right"></el-table-column>
          <el-table-column prop="credit" label="支出" width="110" align="right"></el-table-column>
          <el-table-column prop="balance" label="余额" width="120" align="right"></el-table-column>
        </el-table>
        <div v-if="importResult.invalid" style="margin-top:10px">
          <div style="font-size:13px; font-weight:600; color:var(--zc-danger); margin-bottom:6px">
            错误行（{{ importResult.invalid }}）
          </div>
          <el-table :data="importResult.errors" border size="small" height="150">
            <el-table-column prop="row" label="行号" width="70"></el-table-column>
            <el-table-column prop="message" label="问题说明" min-width="260"></el-table-column>
          </el-table>
        </div>
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
            确认导入（{{ importResult ? importResult.valid : 0 }} 条）
          </el-button>
        </template>
      </template>
    </el-dialog>
  </div>
  `,
});
