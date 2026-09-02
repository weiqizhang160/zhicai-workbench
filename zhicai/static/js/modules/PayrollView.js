// 工资社保（项目书 6.10 / 7.11）：批次 → 员工行 → 个税自动算 → 确认生成计提/发放凭证
window.PayrollView = Vue.defineComponent({
  name: 'PayrollView',
  data() {
    return {
      loading: false,
      batches: [],
      stateFilter: '',
      // 详情
      detailVisible: false,
      batch: null,
      // 员工行弹窗
      lineDialog: false,
      editingLine: null,
      lineForm: null,
      lineSubmitting: false,
      iitPreviewValue: null,
      // 新建批次
      batchDialog: false,
      batchForm: null,
      batchSubmitting: false,
    };
  },
  computed: {
    books() { return (window.ZC_STORE && window.ZC_STORE.books) || []; },
    currentBookId() { return (window.ZC_STORE && window.ZC_STORE.currentBookId) || null; },
    stateMeta() {
      return {
        draft: { label: '草稿', color: '#6C757D', tag: 'info' },
        confirmed: { label: '已确认', color: '#17A2B8', tag: 'primary' },
        paid: { label: '已发放', color: '#28A745', tag: 'success' },
      };
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
        const r = await ZCAPI.payroll.batches({
          book_id: this.currentBookId || null, state: this.stateFilter || null,
        });
        this.batches = r.items || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      }
      this.loading = false;
    },
    openNewBatch() {
      const d = new Date();
      const period = `${d.getFullYear()}-${String(d.getMonth() === 0 ? 12 : d.getMonth()).padStart(2, '0')}`;
      this.batchForm = {
        book_id: this.currentBookId || null, period, remark: '', copy_from_last: false,
      };
      this.batchDialog = true;
    },
    async submitBatch() {
      const f = this.batchForm;
      if (!f.book_id) return ElementPlus.ElMessage.warning('请选择客户账套');
      if (!/^\d{4}-\d{2}$/.test(f.period)) return ElementPlus.ElMessage.warning('期间格式：YYYY-MM');
      this.batchSubmitting = true;
      try {
        const r = await ZCAPI.payroll.createBatch(f);
        ElementPlus.ElMessage.success(
          f.copy_from_last ? '已复制上月工资表' : '工资批次已创建');
        this.batchDialog = false;
        await this.load();
        this.openDetail(r.batch);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '创建失败');
      }
      this.batchSubmitting = false;
    },
    async openDetail(b) {
      try {
        const r = await ZCAPI.payroll.batch(b.id);
        this.batch = r.batch;
        this.detailVisible = true;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      }
    },
    isDraft() { return this.batch && this.batch.state === 'draft'; },

    // ---------- 员工行 ----------
    openNewLine() {
      this.editingLine = null;
      this.lineForm = {
        employee_name: '', id_card_tail: '', gross_salary: '', social_employee: '',
        social_employer: '', fund_employer: '', iit: '', remark: '',
      };
      this.iitPreviewValue = null;
      this.lineDialog = true;
    },
    openEditLine(ln) {
      if (!this.isDraft()) return;
      this.editingLine = ln;
      this.lineForm = {
        employee_name: ln.employee_name, id_card_tail: ln.id_card_tail || '',
        gross_salary: ln.gross_salary, social_employee: ln.social_employee,
        social_employer: ln.social_employer, fund_employer: ln.fund_employer,
        iit: ln.iit, remark: ln.remark || '',
      };
      this.iitPreviewValue = null;
      this.lineDialog = true;
    },
    async previewIit() {
      const f = this.lineForm;
      if (!f.gross_salary) { this.iitPreviewValue = null; return; }
      try {
        const r = await ZCAPI.payroll.iitPreview(f.gross_salary, f.social_employee || '0');
        this.iitPreviewValue = r.iit;
      } catch (e) { this.iitPreviewValue = null; }
    },
    async submitLine() {
      const f = this.lineForm;
      if (!f.employee_name) return ElementPlus.ElMessage.warning('请填写员工姓名');
      if (!f.gross_salary) return ElementPlus.ElMessage.warning('请填写应发工资');
      this.lineSubmitting = true;
      try {
        let r;
        if (this.editingLine) {
          r = await ZCAPI.payroll.updateLine(this.editingLine.id, f);
          ElementPlus.ElMessage.success('已保存');
        } else {
          r = await ZCAPI.payroll.addLine(this.batch.id, f);
          ElementPlus.ElMessage.success('已添加');
        }
        this.batch = r.batch;
        this.lineDialog = false;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.lineSubmitting = false;
    },
    async removeLine(ln) {
      try {
        await ElementPlus.ElMessageBox.confirm('确认删除员工 ' + ln.employee_name + ' 的工资行？',
          '删除工资行', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.payroll.removeLine(ln.id);
        ElementPlus.ElMessage.success('已删除');
        await this.openDetail(this.batch);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },
    async recalc() {
      try {
        const r = await ZCAPI.payroll.recalc(this.batch.id);
        this.batch = r.batch;
        ElementPlus.ElMessage.success('已重算 ' + r.recalculated + ' 名员工的个税');
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '重算失败');
      }
    },
    async confirmBatch() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '确认后系统将生成两张草稿凭证（计提 + 发放），批次将锁定不可再改员工行。继续？',
          '确认工资批次', { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        const r = await ZCAPI.payroll.confirm(this.batch.id);
        this.batch = r.batch;
        ElementPlus.ElMessage.success('已生成计提/发放两张凭证（草稿状态，可在记账模块查看过账）');
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '确认失败');
      }
    },
    async markPaid() {
      try {
        await ElementPlus.ElMessageBox.confirm('确认标记为已发放？', '标记发放',
          { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        const r = await ZCAPI.payroll.markPaid(this.batch.id);
        this.batch = r.batch;
        ElementPlus.ElMessage.success('已标记为已发放');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },
    goMove(id) {
      if (id) location.hash = '#/move/' + id;
    },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><wallet></wallet></el-icon>
          <div>
            <div style="font-size:16px; font-weight:600">工资社保</div>
            <div style="font-size:12px; color:var(--zc-text-2)">
              按客户按月建批次 → 录员工行（个税自动算）→ 确认生成计提/发放凭证
            </div>
          </div>
        </div>
        <div style="flex:1"></div>
        <el-select v-model="stateFilter" placeholder="全部状态" clearable size="small"
                   style="width:130px" @change="load">
          <el-option label="草稿" value="draft"></el-option>
          <el-option label="已确认" value="confirmed"></el-option>
          <el-option label="已发放" value="paid"></el-option>
        </el-select>
        <el-button size="small" type="primary" @click="openNewBatch">
          <el-icon><plus></plus></el-icon> 新建工资批次
        </el-button>
      </div>

      <el-table :data="batches" size="small" border stripe v-loading="loading"
                style="cursor:pointer" @row-click="openDetail">
        <el-table-column prop="period" label="期间" width="80"></el-table-column>
        <el-table-column prop="book_name" label="客户" min-width="130"></el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="stateMeta[row.state] && stateMeta[row.state].tag">
              {{ stateMeta[row.state] ? stateMeta[row.state].label : row.state }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="employee_count" label="人数" width="60" align="right"></el-table-column>
        <el-table-column prop="total_gross" label="应发合计" width="110" align="right">
          <template #default="{row}">{{ fmt(row.total_gross) }}</template>
        </el-table-column>
        <el-table-column prop="total_net" label="实发合计" width="110" align="right">
          <template #default="{row}">{{ fmt(row.total_net) }}</template>
        </el-table-column>
        <el-table-column prop="social_base" label="社保公积金基数" width="120" align="right">
          <template #default="{row}">{{ fmt(row.social_base) }}</template>
        </el-table-column>
        <el-table-column label="凭证" width="130">
          <template #default="{row}">
            <el-link v-if="row.accrual_move_id" type="primary" style="font-size:12px"
                     @click.stop="goMove(row.accrual_move_id)">计提#{{ row.accrual_move_id }}</el-link>
            <el-link v-if="row.payment_move_id" type="primary" style="font-size:12px; margin-left:6px"
                     @click.stop="goMove(row.payment_move_id)">发放#{{ row.payment_move_id }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip></el-table-column>
      </el-table>
    </div>

    <!-- 新建批次 -->
    <el-dialog v-model="batchDialog" title="新建工资批次" width="460px">
      <el-form v-if="batchForm" label-position="top" size="small">
        <el-form-item label="客户账套" required>
          <el-select v-model="batchForm.book_id" filterable style="width:100%"
                     placeholder="选择客户">
            <el-option v-for="b in books" :key="b.id" :value="b.id"
                       :label="b.code + ' ' + b.short_name"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="期间（年-月）" required>
              <el-input v-model="batchForm.period" placeholder="2026-09"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label=" ">
              <el-checkbox v-model="batchForm.copy_from_last">复制上月员工行</el-checkbox>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="batchForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialog = false">取消</el-button>
        <el-button type="primary" :loading="batchSubmitting" @click="submitBatch">创建</el-button>
      </template>
    </el-dialog>

    <!-- 批次详情 -->
    <el-dialog v-model="detailVisible" width="900px" top="5vh"
               :title="batch ? batch.period + ' 工资表 · ' + (batch.book_name || '') : ''">
      <template v-if="batch">
        <div style="display:flex; gap:20px; margin-bottom:10px; font-size:13px; align-items:center">
          <el-tag size="small" :type="stateMeta[batch.state] && stateMeta[batch.state].tag">
            {{ stateMeta[batch.state] ? stateMeta[batch.state].label : batch.state }}
          </el-tag>
          <span>人数：<b>{{ batch.employee_count }}</b></span>
          <span>应发：<b>¥{{ fmt(batch.total_gross) }}</b></span>
          <span>实发：<b style="color:var(--zc-success)">¥{{ fmt(batch.total_net) }}</b></span>
          <span>社保基数：¥{{ fmt(batch.social_base) }}</span>
          <div style="flex:1"></div>
          <template v-if="batch.state === 'draft'">
            <el-button size="small" @click="openNewLine">+ 员工行</el-button>
            <el-button size="small" @click="recalc">重算个税</el-button>
            <el-button size="small" type="primary" @click="confirmBatch">确认生成凭证</el-button>
          </template>
          <el-button v-else-if="batch.state === 'confirmed'" size="small" type="success"
                     @click="markPaid">标记已发放</el-button>
        </div>

        <el-table :data="batch.lines || []" size="small" border stripe
                  :row-style="isDraft() ? {cursor:'pointer'} : {}" @row-click="openEditLine">
          <el-table-column prop="employee_name" label="员工" min-width="90"></el-table-column>
          <el-table-column prop="id_card_tail" label="证件尾号" width="80"></el-table-column>
          <el-table-column prop="gross_salary" label="应发工资" width="100" align="right">
            <template #default="{row}">{{ fmt(row.gross_salary) }}</template>
          </el-table-column>
          <el-table-column prop="social_employee" label="个人社保" width="90" align="right">
            <template #default="{row}">{{ fmt(row.social_employee) }}</template>
          </el-table-column>
          <el-table-column prop="iit" label="个税" width="80" align="right">
            <template #default="{row}">{{ fmt(row.iit) }}</template>
          </el-table-column>
          <el-table-column prop="net_salary" label="实发" width="100" align="right">
            <template #default="{row}">
              <b style="color:var(--zc-success)">{{ fmt(row.net_salary) }}</b>
            </template>
          </el-table-column>
          <el-table-column prop="social_employer" label="单位社保" width="90" align="right">
            <template #default="{row}">{{ fmt(row.social_employer) }}</template>
          </el-table-column>
          <el-table-column prop="fund_employer" label="单位公积金" width="90" align="right">
            <template #default="{row}">{{ fmt(row.fund_employer) }}</template>
          </el-table-column>
          <el-table-column v-if="isDraft()" label="操作" width="60" fixed="right">
            <template #default="{row}">
              <el-button link type="danger" size="small" @click.stop="removeLine(row)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="isDraft()" style="font-size:12px; color:var(--zc-text-3); margin-top:6px">
          点击行可编辑；个税 = (应发 − 5000 起征 − 个人社保) 按月度预扣率表计算，税率表可在系统参数中更新
        </div>
      </template>
    </el-dialog>

    <!-- 员工行编辑 -->
    <el-dialog v-model="lineDialog" :title="editingLine ? '编辑员工行' : '添加员工行'" width="560px">
      <el-form v-if="lineForm" label-position="top" size="small">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="员工姓名" required>
              <el-input v-model="lineForm.employee_name"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="身份证尾号（6 位）">
              <el-input v-model="lineForm.id_card_tail" maxlength="6"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="应发工资" required>
              <el-input v-model="lineForm.gross_salary" @change="previewIit"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="个人社保（三险）">
              <el-input v-model="lineForm.social_employee" @change="previewIit"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <div v-if="iitPreviewValue !== null"
             style="font-size:12px; color:var(--zc-primary); margin-bottom:8px">
          个税试算：¥{{ fmt(iitPreviewValue) }}（实发 ≈ ¥{{ fmt((parseFloat(lineForm.gross_salary)||0) - (parseFloat(lineForm.social_employee)||0) - (parseFloat(iitPreviewValue)||0)) }}）
        </div>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="单位社保">
              <el-input v-model="lineForm.social_employer"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="单位公积金">
              <el-input v-model="lineForm.fund_employer"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="个税（留空自动算）">
              <el-input v-model="lineForm.iit" placeholder="自动"></el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="lineForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="lineDialog = false">取消</el-button>
        <el-button type="primary" :loading="lineSubmitting" @click="submitLine">保存</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
