// 新建客户向导（项目书 7.3：填基本信息 → 选会计准则 → 一键初始化账套）
window.BookWizard = Vue.defineComponent({
  name: 'BookWizard',
  emits: ['created'],
  template: `
  <el-dialog v-model="visible" title="新建客户（账套）" width="640px" :close-on-click-modal="false">
    <el-steps :active="step" finish-status="success" align-center style="margin-bottom: 22px">
      <el-step title="基本信息"></el-step>
      <el-step title="初始化账套"></el-step>
    </el-steps>

    <!-- 第一步：基本信息 -->
    <el-form v-if="step === 0" label-position="top">
      <div class="form-grid">
        <el-form-item label="公司全称" required>
          <el-input v-model="form.name" placeholder="如：深圳市XX贸易有限公司"></el-input>
        </el-form-item>
        <el-form-item label="简称" required>
          <el-input v-model="form.short_name" placeholder="顶栏切换器显示名"></el-input>
        </el-form-item>
        <el-form-item label="统一社会信用代码">
          <el-input v-model="form.credit_no" maxlength="18" placeholder="重复税号会拦截"></el-input>
        </el-form-item>
        <el-form-item label="纳税人类型" required>
          <el-select v-model="form.taxpayer_type" style="width: 100%">
            <el-option label="小规模纳税人" value="small"></el-option>
            <el-option label="一般纳税人" value="general"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="法定代表人">
          <el-input v-model="form.legal_person"></el-input>
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="form.phone"></el-input>
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="如：批发零售 / 建筑 / 软件"></el-input>
        </el-form-item>
        <el-form-item label="接账起始月份">
          <el-date-picker v-model="form.bookkeeping_start" type="month" value-format="YYYY-MM-DD"
                          style="width: 100%"></el-date-picker>
        </el-form-item>
        <el-form-item label="注册地址" class="full-col">
          <el-input v-model="form.address"></el-input>
        </el-form-item>
        <el-form-item label="外贸客户">
          <el-switch v-model="form.is_foreign_trade"></el-switch>
          <span style="font-size:12px;color:var(--zc-text-2);margin-left:8px">
            开通后解锁外贸专区（报关单/收汇/退税台账，M6 交付）
          </span>
        </el-form-item>
      </div>
    </el-form>

    <!-- 第二步：确认初始化 -->
    <div v-if="step === 1">
      <el-alert type="info" :closable="false" style="margin-bottom: 16px"
                title="点击「完成初始化」后系统将自动执行以下动作（一个事务，失败自动回滚）：">
      </el-alert>
      <el-card shadow="never" style="margin-bottom: 12px">
        <div class="dash-row"><span>① 创建客户账套 {{ codeHint }}</span><span>{{ form.short_name || form.name }}</span></div>
        <div class="dash-row"><span>② 克隆会计科目表（小企业准则 87 个科目，含应交税费全套明细）</span><span style="color:var(--zc-success)">自动</span></div>
        <div class="dash-row"><span>③ 创建默认账簿（记 / 收 / 付 / 转 四个凭证字）</span><span style="color:var(--zc-success)">自动</span></div>
        <div class="dash-row"><span>④ 初始化凭证自动编号器</span><span style="color:var(--zc-success)">自动</span></div>
      </el-card>
      <el-form label-position="top">
        <el-form-item label="会计准则">
          <el-radio-group v-model="form.accounting_standard">
            <el-radio value="small">小企业会计准则（推荐，小微客户通用）</el-radio>
            <el-radio value="enterprise">企业会计准则</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button v-if="step === 0" @click="step = 1" type="primary" :disabled="!form.name">下一步</el-button>
      <el-button v-if="step === 1" @click="step = 0">上一步</el-button>
      <el-button v-if="step === 1" type="primary" :loading="creating" @click="submit">
        完成初始化
      </el-button>
    </template>
  </el-dialog>
  `,
  data() {
    return {
      visible: false,
      step: 0,
      creating: false,
      form: {
        name: '', short_name: '', credit_no: '', taxpayer_type: 'small',
        accounting_standard: 'small', is_foreign_trade: false,
        industry: '', legal_person: '', phone: '', address: '',
        bookkeeping_start: null, remark: '',
      },
    };
  },
  computed: {
    codeHint() { return '（编号自动分配）'; },
  },
  methods: {
    open() {
      this.step = 0;
      this.creating = false;
      this.form = {
        name: '', short_name: '', credit_no: '', taxpayer_type: 'small',
        accounting_standard: 'small', is_foreign_trade: false,
        industry: '', legal_person: '', phone: '', address: '',
        bookkeeping_start: null, remark: '',
      };
      this.visible = true;
    },
    async submit() {
      this.creating = true;
      try {
        const res = await ZCAPI.createBook(this.form);
        this.visible = false;
        ElementPlus.ElMessageBox.alert(
          '客户【' + res.book.short_name + '】创建成功：已初始化 ' + res.account_count +
          ' 个会计科目、4 个账簿（记/收/付/转）。', '初始化完成',
          { type: 'success', confirmButtonText: '好的' });
        this.$emit('created', res.book);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '创建失败');
      } finally {
        this.creating = false;
      }
    },
  },
});
