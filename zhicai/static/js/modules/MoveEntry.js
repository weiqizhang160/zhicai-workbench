// 凭证录入定制页（项目书 7.5）：类 Excel 连续录入，不用通用 FormView。
//
// 关键交互：
//  1. 摘要输入 `//` → 自动复制上一行摘要
//  2. 科目联想：编码 / 名称匹配，仅末级科目可记账
//  3. 借贷互斥：输入一侧自动清空另一侧
//  4. 回车自动加行并聚焦下一行
//  5. 底栏实时合计，不平衡时【保存并过账】禁用（保存仍可用，支持暂存草稿）
//  6. 已过账只读，唯一出路是红冲
window.MoveEntry = Vue.defineComponent({
  name: 'MoveEntry',
  props: {
    table: String,
    recordId: { type: Number, default: null },
    mode: { type: String, default: 'new' },
  },
  data() {
    return {
      loading: false,
      saving: false,
      moveId: null,
      state: 'draft',            // draft / posted / voided
      moveName: '',              // 凭证号（过账后才有）
      sourceType: 'manual',
      reversedMoveId: null,
      journals: [],
      accounts: [],              // 末级科目（联想数据源）
      partners: [],
      templates: [],
      form: { journal_id: null, move_date: '', attachment_count: 0, remark: '' },
      lines: [],
      // 模板
      tplDialog: false,
      tplName: '',
    };
  },
  computed: {
    isEdit() { return !!this.moveId; },
    readonly() { return this.state !== 'draft'; },
    totalDebit() {
      return this.lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0);
    },
    totalCredit() {
      return this.lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0);
    },
    diff() { return this.totalDebit - this.totalCredit; },
    balanced() { return Math.abs(this.diff) < 0.005; },
    hasAmount() { return this.totalDebit > 0 || this.totalCredit > 0; },
    stateTag() {
      return { draft: '草稿', posted: '已过账', voided: '已红冲' }[this.state] || this.state;
    },
    stateTagType() {
      return { draft: 'info', posted: 'success', voided: 'danger' }[this.state] || 'info';
    },
  },
  watch: {
    recordId() { this.init(); },
  },
  mounted() { this.init(); },
  methods: {
    todayStr() {
      const d = new Date();
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    },
    money(v) {
      const n = parseFloat(v) || 0;
      return n.toFixed(2);
    },
    fmt(v) { return (parseFloat(v) || 0).toFixed(2); },

    blankLine() {
      return { summary: '', account_id: null, account_label: '',
               partner_id: null, debit: '', credit: '' };
    },

    async init() {
      this.loading = true;
      try {
        // 基础数据并行加载
        const [jr, ac, pa, tp] = await Promise.all([
          ZCAPI.acc.journals(),
          ZCAPI.acc.leafAccounts(''),
          ZCAPI.acc.partners(''),
          ZCAPI.acc.templates(),
        ]);
        this.journals = jr.journals || [];
        this.accounts = ac.accounts || [];
        this.partners = (pa.records || []).map((r) => ({ id: r.id, name: r.name }));
        this.templates = tp.templates || [];
        if (!this.form.journal_id && this.journals.length) {
          this.form.journal_id = this.journals[0].id;
        }
      } catch (e) {
        // 未选账套时会报 book_required，给明确提示
        ElementPlus.ElMessage.warning(e.message || '加载基础数据失败');
      }

      this.moveId = this.recordId || null;
      if (this.moveId) {
        try {
          const res = await ZCAPI.acc.move(this.moveId);
          this.applyMove(res.move);
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '加载凭证失败');
        }
      } else {
        this.resetBlank();
      }
      this.loading = false;
    },

    applyMove(m) {
      this.form.journal_id = m.journal_id;
      this.form.move_date = m.move_date;
      this.form.attachment_count = m.attachment_count || 0;
      this.form.remark = m.remark || '';
      this.state = m.state;
      this.moveName = m.name || '';
      this.sourceType = m.source_type;
      this.reversedMoveId = m.reversed_move_id;
      this.lines = (m.lines || []).map((l) => ({
        summary: l.summary || '',
        account_id: l.account_id,
        account_label: l.account_display || (l.account_code ? `${l.account_code} ${l.account_name}` : ''),
        partner_id: l.partner_id || null,
        debit: parseFloat(l.debit) ? String(parseFloat(l.debit)) : '',
        credit: parseFloat(l.credit) ? String(parseFloat(l.credit)) : '',
      }));
      while (this.lines.length < 4) this.lines.push(this.blankLine());
    },

    resetBlank() {
      this.state = 'draft';
      this.moveName = '';
      this.moveId = null;
      this.reversedMoveId = null;
      this.form = { journal_id: this.journals.length ? this.journals[0].id : null,
                    move_date: this.todayStr(), attachment_count: 0, remark: '' };
      this.lines = [this.blankLine(), this.blankLine(), this.blankLine(), this.blankLine()];
    },

    // ---------- 分录编辑 ----------
    addLine() { this.lines.push(this.blankLine()); },
    removeLine(i) {
      if (this.lines.length <= 1) return;
      this.lines.splice(i, 1);
    },

    // 摘要输入 `//` → 复制上一行摘要（项目书 7.5）
    onSummaryInput(i) {
      const ln = this.lines[i];
      if (ln.summary === '//') {
        ln.summary = i > 0 ? (this.lines[i - 1].summary || '') : '';
      }
    },

    // 借贷互斥：输入一侧自动清空另一侧
    onDebitInput(i) { if (this.lines[i].debit) this.lines[i].credit = ''; },
    onCreditInput(i) { if (this.lines[i].credit) this.lines[i].debit = ''; },

    // 回车：最后一行则自动加行，并聚焦下一行摘要框（类 Excel 连续录入）
    onEnter(i) {
      if (i === this.lines.length - 1) this.addLine();
      this.$nextTick(() => {
        const ref = this.$refs['summary' + (i + 1)];
        const el = Array.isArray(ref) ? ref[0] : ref;
        if (el && el.focus) el.focus();
      });
    },

    // ---------- 科目联想（仅末级） ----------
    queryAccount(kw, cb) {
      const k = (kw || '').trim();
      let list = this.accounts;
      if (k) {
        list = list.filter((a) =>
          a.code.indexOf(k) === 0 || a.name.indexOf(k) >= 0 || a.display.indexOf(k) >= 0);
      }
      cb(list.slice(0, 30).map((a) => ({ value: a.display, id: a.id, code: a.code,
                                          name: a.name, aux: a.aux_partner })));
    },
    onAccountSelect(i, item) {
      const ln = this.lines[i];
      ln.account_id = item.id;
      ln.account_label = item.value;
      // 科目不需要往来单位时清掉，避免脏数据
      if (!item.aux) ln.partner_id = null;
    },
    onAccountBlur(i) {
      // 手输文本无法匹配到具体科目时清空 id（草稿允许，过账时后端会拦截）
      const ln = this.lines[i];
      if (ln.account_label && !this.accounts.some((a) => a.display === ln.account_label)) {
        ln.account_id = null;
      }
    },
    needPartner(i) {
      const ln = this.lines[i];
      const acc = this.accounts.find((a) => a.id === ln.account_id);
      return !!(acc && acc.aux_partner);
    },

    // ---------- 保存 / 过账 / 红冲 ----------
    payload() {
      const lines = this.lines
        .filter((l) => l.summary || l.account_id || parseFloat(l.debit) || parseFloat(l.credit))
        .map((l) => ({
          summary: (l.summary || '').trim(),
          account_id: l.account_id || null,
          partner_id: l.partner_id || null,
          debit: l.debit === '' ? '0' : String(l.debit),
          credit: l.credit === '' ? '0' : String(l.credit),
        }));
      return {
        journal_id: this.form.journal_id,
        move_date: this.form.move_date,
        attachment_count: parseInt(this.form.attachment_count, 10) || 0,
        remark: this.form.remark || null,
        lines,
      };
    },

    async save(withPost) {
      if (!this.form.journal_id) return ElementPlus.ElMessage.warning('请选择凭证字');
      if (!this.form.move_date) return ElementPlus.ElMessage.warning('请选择凭证日期');
      if (!this.payload().lines.length) return ElementPlus.ElMessage.warning('请至少录入一行分录');

      this.saving = true;
      try {
        let res;
        if (this.moveId) {
          res = await ZCAPI.acc.updateMove(this.moveId, this.payload());
        } else {
          res = await ZCAPI.acc.createMove(this.payload());
          this.moveId = res.move.id;
        }
        this.state = res.move.state;
        this.moveName = res.move.name || this.moveName;

        if (withPost) {
          const p = await ZCAPI.acc.postMove(this.moveId);
          this.state = p.move.state;
          this.moveName = p.move.name;
          ElementPlus.ElMessage.success(`已过账，凭证号 ${this.moveName}`);
        } else {
          ElementPlus.ElMessage.success(this.moveId ? '已保存' : '已保存为草稿');
        }
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.saving = false;
    },

    async doReverse() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '红冲将生成一张反向凭证，原凭证置为已红冲且不可再编辑。确认继续？',
          '红冲确认', { type: 'warning' });
      } catch (e) { return; }
      try {
        const res = await ZCAPI.acc.reverseMove(this.moveId);
        ElementPlus.ElMessage.success(`已生成红冲凭证 ${res.move.name}`);
        location.hash = '#/move/' + res.move.id;
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '红冲失败');
      }
    },

    // ---------- 凭证模板 ----------
    openTplDialog() {
      if (!this.payload().lines.length) return ElementPlus.ElMessage.warning('请先录入分录');
      this.tplName = '';
      this.tplDialog = true;
    },
    async confirmSaveTpl() {
      if (!this.tplName.trim()) return ElementPlus.ElMessage.warning('请填写模板名称');
      try {
        const lines = this.lines
          .filter((l) => l.summary || l.account_id)
          .map((l) => ({ summary: l.summary, account_id: l.account_id,
                         partner_id: l.partner_id, debit: '0', credit: '0' }));
        await ZCAPI.acc.saveTemplate({
          template_name: this.tplName.trim(),
          journal_id: this.form.journal_id,
          move_date: this.form.move_date,
          lines,
        });
        ElementPlus.ElMessage.success('已存为常用模板');
        this.tplDialog = false;
        const tp = await ZCAPI.acc.templates();
        this.templates = tp.templates || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存模板失败');
      }
    },
    loadTemplate(tpl) {
      this.form.journal_id = tpl.journal_id;
      this.lines = (tpl.lines || []).map((l) => ({
        summary: l.summary || '', account_id: l.account_id,
        account_label: l.account_display || '', partner_id: l.partner_id || null,
        debit: '', credit: '',
      }));
      while (this.lines.length < 4) this.lines.push(this.blankLine());
      ElementPlus.ElMessage.success(`已套用模板「${tpl.template_name}」（金额需重新录入）`);
    },

    goList() { location.hash = '#/list/account_move'; },
  },
  template: `
  <div class="view-card">
    <!-- 标题栏 -->
    <div class="form-head">
      <div style="display:flex; align-items:center; gap:10px">
        <el-icon style="font-size:22px; color:var(--zc-primary)"><edit-pen></edit-pen></el-icon>
        <div>
          <div style="font-size:16px; font-weight:600">
            {{ isEdit ? (moveName || '编辑凭证') : '新增记账凭证' }}
          </div>
          <div style="font-size:12px; color:var(--zc-text-2)">
            {{ isEdit ? '凭证 #' + moveId : '类 Excel 连续录入，回车自动加行，摘要输入 // 复制上一行' }}
          </div>
        </div>
        <el-tag :type="stateTagType" size="small" style="margin-left:6px">{{ stateTag }}</el-tag>
        <el-tag v-if="reversedMoveId" type="danger" size="small">已被红冲</el-tag>
      </div>
      <div style="flex:1"></div>
      <el-button size="small" @click="goList">返回列表</el-button>
    </div>

    <!-- 表头 -->
    <el-form :inline="true" size="small" style="margin: 12px 0">
      <el-form-item label="凭证字">
        <el-select v-model="form.journal_id" style="width:150px" :disabled="readonly">
          <el-option v-for="j in journals" :key="j.id" :label="j.name + '（' + j.code + '）'" :value="j.id"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="日期">
        <el-date-picker v-model="form.move_date" type="date" value-format="YYYY-MM-DD"
                        style="width:160px" :disabled="readonly"></el-date-picker>
      </el-form-item>
      <el-form-item label="附件数">
        <el-input-number v-model="form.attachment_count" :min="0" :max="999"
                         style="width:120px" :disabled="readonly"></el-input-number>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" style="width:240px" placeholder="备查说明（选填）"
                  :disabled="readonly"></el-input>
      </el-form-item>
      <el-form-item v-if="!readonly && templates.length">
        <el-dropdown @command="loadTemplate">
          <el-button size="small">套用模板<el-icon class="el-icon--right"><arrow-down></arrow-down></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-for="t in templates" :key="t.id" :command="t">
                {{ t.template_name }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-form-item>
    </el-form>

    <!-- 分录表格（类 Excel） -->
    <el-table :data="lines" border size="small" style="width:100%">
      <el-table-column label="#" width="50" align="center">
        <template #default="{ $index }">
          <span style="color:var(--zc-text-2)">{{ $index + 1 }}</span>
        </template>
      </el-table-column>

      <el-table-column label="摘要" min-width="200">
        <template #default="{ row, $index }">
          <el-input v-model="row.summary" :ref="'summary' + $index" size="small"
                    placeholder="摘要（输入 // 复制上一行）" :disabled="readonly"
                    @input="onSummaryInput($index)" @keyup.enter="onEnter($index)"></el-input>
        </template>
      </el-table-column>

      <el-table-column label="会计科目（末级）" min-width="260">
        <template #default="{ row, $index }">
          <el-autocomplete v-model="row.account_label" :fetch-suggestions="queryAccount"
                           @select="(it) => onAccountSelect($index, it)"
                           @blur="onAccountBlur($index)"
                           style="width:100%" size="small"
                           placeholder="输入编码或名称，如 1001 / 银行存款"
                           :disabled="readonly"
                           :trigger-on-focus="true"></el-autocomplete>
        </template>
      </el-table-column>

      <el-table-column label="往来单位" width="170">
        <template #default="{ row, $index }">
          <el-select v-if="needPartner($index)" v-model="row.partner_id" size="small"
                     filterable clearable placeholder="必填" style="width:100%"
                     :disabled="readonly">
            <el-option v-for="p in partners" :key="p.id" :label="p.name" :value="p.id"></el-option>
          </el-select>
          <span v-else style="color:var(--zc-text-3); font-size:12px">—</span>
        </template>
      </el-table-column>

      <el-table-column label="借方金额" width="150" align="right">
        <template #default="{ row, $index }">
          <el-input v-model="row.debit" size="small" placeholder="0.00" :disabled="readonly"
                    @input="onDebitInput($index)" @keyup.enter="onEnter($index)"
                    style="text-align:right"></el-input>
        </template>
      </el-table-column>

      <el-table-column label="贷方金额" width="150" align="right">
        <template #default="{ row, $index }">
          <el-input v-model="row.credit" size="small" placeholder="0.00" :disabled="readonly"
                    @input="onCreditInput($index)" @keyup.enter="onEnter($index)"
                    style="text-align:right"></el-input>
        </template>
      </el-table-column>

      <el-table-column label="" width="56" align="center">
        <template #default="{ $index }">
          <el-button link type="danger" :disabled="readonly || lines.length <= 1"
                     @click="removeLine($index)">
            <el-icon><delete></delete></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top:8px">
      <el-button size="small" :disabled="readonly" @click="addLine">
        <el-icon><plus></plus></el-icon> 加一行
      </el-button>
    </div>

    <!-- 底栏合计 -->
    <div class="move-total-bar">
      <div class="total-item">
        <span class="label">借方合计</span>
        <span class="value">{{ fmt(totalDebit) }}</span>
      </div>
      <div class="total-item">
        <span class="label">贷方合计</span>
        <span class="value">{{ fmt(totalCredit) }}</span>
      </div>
      <div class="total-item">
        <span class="label">差额</span>
        <span class="value" :class="balanced ? 'ok' : 'bad'">{{ fmt(diff) }}</span>
      </div>
      <div style="flex:1"></div>
      <div v-if="!balanced && hasAmount" class="balance-warn">
        <el-icon><warning-filled></warning-filled></el-icon>
        借贷不平衡，差额 {{ fmt(diff) }}，无法过账
      </div>
    </div>

    <!-- 操作按钮 -->
    <div style="margin-top:14px; display:flex; gap:8px">
      <el-button type="primary" :loading="saving" :disabled="readonly" @click="save(false)">
        保存
      </el-button>
      <el-button type="success" :loading="saving"
                 :disabled="readonly || !balanced || !hasAmount" @click="save(true)">
        保存并过账
      </el-button>
      <el-button :disabled="readonly || !hasAmount" @click="openTplDialog">存为模板</el-button>
      <div style="flex:1"></div>
      <el-button type="danger" v-if="state === 'posted'" @click="doReverse">红冲</el-button>
      <el-button v-if="!isEdit" @click="resetBlank">重填</el-button>
    </div>

    <!-- 存为模板弹窗 -->
    <el-dialog v-model="tplDialog" title="存为常用凭证模板" width="420px">
      <el-form label-position="top">
        <el-form-item label="模板名称" required>
          <el-input v-model="tplName" placeholder="如：每月计提折旧"></el-input>
        </el-form-item>
      </el-form>
      <div style="font-size:12px; color:var(--zc-text-2)">
        模板只保存科目与摘要，不保存金额（套用后需重新录入金额）。
      </div>
      <template #footer>
        <el-button @click="tplDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmSaveTpl">保存模板</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
