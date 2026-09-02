// 通用表单视图渲染器（项目书 8.2 FormView 规范：分组字段 + 状态徽章 + 活动日志面板）
window.FormView = Vue.defineComponent({
  name: 'FormView',
  props: {
    table: { type: String, required: true },
    recordId: { type: [Number, String], default: null },
  },
  template: `
  <div class="view-card" v-if="meta">
    <!-- 页头 -->
    <div class="form-head">
      <el-icon size="22" color="#714B67"><document></document></el-icon>
      <span class="form-title">{{ title }}</span>
      <span class="zc-badge" v-if="badge">
        <span class="dot" :style="{background: badge.color}"></span>{{ badge.label }}
      </span>
      <div class="spacer"></div>
      <el-button v-if="!isNew" type="danger" plain @click="onDelete">归档</el-button>
      <el-button type="primary" @click="save" :loading="saving">保存</el-button>
    </div>

    <!-- 字段分组 -->
    <div class="form-groups">
      <div v-for="group in groups" :key="group.label">
        <div class="form-group-title">{{ group.label }}</div>
        <div class="form-grid">
          <div v-for="name in group.fields" :key="name" class="field-cell"
               :class="{'full-col': fieldOf(name).type === 'text'}">
            <el-form-item :label="fieldOf(name).label" :required="!!fieldOf(name).required"
                          label-position="top" style="margin-bottom: 12px;">
              <!-- char -->
              <el-input v-model="form[name]" v-if="fieldOf(name).type === 'char'"
                        :disabled="readonlyField(name)" :placeholder="fieldOf(name).placeholder || ''">
              </el-input>
              <!-- text -->
              <el-input v-model="form[name]" v-if="fieldOf(name).type === 'text'" type="textarea"
                        :rows="3" :disabled="readonlyField(name)">
              </el-input>
              <!-- selection -->
              <el-select v-model="form[name]" v-if="fieldOf(name).type === 'selection'"
                         :disabled="readonlyField(name)" style="width: 100%">
                <el-option v-for="o in fieldOf(name).options" :key="o.value"
                           :label="o.label" :value="o.value"></el-option>
              </el-select>
              <!-- boolean -->
              <el-switch v-model="form[name]" v-if="fieldOf(name).type === 'boolean'"
                         :disabled="readonlyField(name)"></el-switch>
              <!-- date -->
              <el-date-picker v-model="form[name]" v-if="fieldOf(name).type === 'date'"
                              type="date" value-format="YYYY-MM-DD" style="width: 100%"
                              :disabled="readonlyField(name)"></el-date-picker>
              <!-- integer / decimal -->
              <el-input-number v-model="form[name]" v-if="['integer','decimal'].includes(fieldOf(name).type)"
                               :controls="false" style="width: 100%" :disabled="readonlyField(name)">
              </el-input-number>
              <!-- many2one -->
              <el-select v-model="form[name]" v-if="fieldOf(name).type === 'many2one'"
                         filterable clearable style="width: 100%">
                <el-option v-for="opt in m2oOptions(fieldOf(name).relation)" :key="opt.id"
                           :label="opt.label" :value="opt.id"></el-option>
              </el-select>
              <!-- 只读系统字段 -->
              <el-input v-if="fieldOf(name).system" :model-value="String(form[name] ?? '')" disabled></el-input>
              <div class="field-help" v-if="fieldOf(name).help"
                   style="font-size:12px;color:var(--zc-text-2);margin-top:2px;">
                {{ fieldOf(name).help }}
              </div>
            </el-form-item>
          </div>
        </div>
      </div>
    </div>

    <!-- 活动日志（Chatter，对标 Odoo mail.thread） -->
    <div class="chatter-panel" v-if="!isNew">
      <div class="chatter-title">活动日志</div>
      <div class="chatter-input">
        <el-input v-model="noteBody" placeholder="添加备注…（回车发送）"
                  @keyup.enter="submitNote" clearable></el-input>
        <el-button @click="submitNote" :loading="noting">留言</el-button>
      </div>
      <div class="chatter-list">
        <div class="chatter-item" v-for="item in chatter" :key="item.id">
          <div class="chatter-avatar">{{ avatarOf(item) }}</div>
          <div class="chatter-body">
            <div class="chatter-meta">
              {{ whoOf(item) }} · {{ item.created_at || '' }}
              <el-tag v-if="item.kind === 'log'" size="small" type="info" style="margin-left:4px">
                {{ actionLabel(item.action) }}
              </el-tag>
            </div>
            <!-- 留言 -->
            <div class="chatter-note" v-if="item.kind === 'note'">{{ item.body }}</div>
            <!-- 字段变更 -->
            <div v-if="item.kind === 'log' && changesArray(item).length">
              <div class="chatter-diff" v-for="(c, i) in changesArray(item)" :key="i">
                <b>{{ fieldLabel(c.field) }}</b>：
                <span class="old">{{ short(c.old) }}</span>
                <span style="margin:0 4px">→</span>
                <span class="new">{{ short(c.new) }}</span>
              </div>
              <div class="chatter-diff" v-if="item.action === 'init'" style="color:var(--zc-success)">
                {{ initMessage(item) }}
              </div>
            </div>
            <div class="chatter-diff" v-if="item.kind === 'log' && item.action === 'init' && !changesArray(item).length">
              {{ initMessage(item) }}
            </div>
          </div>
        </div>
        <div class="empty-state" v-if="!chatter.length" style="padding: 24px 0">
          <div>暂无活动记录</div>
        </div>
      </div>
    </div>
  </div>
  `,
  data() {
    return {
      meta: null,
      form: {},
      chatter: [],
      saving: false,
      noting: false,
      noteBody: '',
      m2oCache: {},
    };
  },
  computed: {
    isNew() { return !this.recordId; },
    groups() {
      if (!this.meta) return [];
      const v = this.meta.views && this.meta.views.form;
      if (v && v.groups) return v.groups;
      // 兜底：全部字段一组
      const names = Object.keys(this.meta.fields).filter((n) => !this.meta.fields[n].system);
      return [{ label: '基本信息', fields: names }];
    },
    title() {
      const label = this.meta ? this.meta.label : '';
      if (this.isNew) return '新建' + label;
      const rec = this.recordData || {};
      return rec._rec_name || (label + ' #' + this.recordId);
    },
    recordData() { return this._recordData || {}; },
    badge() {
      // 状态徽章（8.2：按 state 动态显示）——M1 支持已声明的枚举状态字段
      if (!this.meta || this.isNew) return null;
      for (const kind of ['charge_status', 'partner_type', 'journal_type', 'taxpayer_type']) {
        if (this.form[kind] !== undefined) {
          return window.zcState(kind, this.form[kind]);
        }
      }
      return null;
    },
  },
  methods: {
    fieldOf(name) { return (this.meta && this.meta.fields[name]) || { label: name, type: 'char' }; },
    fieldLabel(name) {
      const f = this.fieldOf(name);
      return f.label || name;
    },
    readonlyField(name) {
      const f = this.fieldOf(name);
      return f.readonly && !this.isNew ? true : (f.readonly && this.isNew && name === 'code' ? true : false);
    },
    short(v) {
      if (v === null || v === undefined || v === '') return '空';
      const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
      return s.length > 40 ? s.slice(0, 40) + '…' : s;
    },
    actionLabel(a) {
      return { create: '创建', write: '修改', init: '初始化', post: '过账' }[a] || a;
    },
    // 后端 changes 有两种形态，必须都兼容：
    //   write 日志 -> 数组 [{field, old, new}]
    //   init  日志 -> 对象 {message: "..."}
    // 旧写法 (item.changes || []) 对对象是 truthy 不兜底，会触发 .find is not a function 导致整页白屏
    changesArray(item) {
      return Array.isArray(item && item.changes) ? item.changes : [];
    },
    initMessage(item) {
      const ch = item && item.changes;
      if (Array.isArray(ch)) {
        const c = ch.find((x) => x.field === 'message');
        return c ? (c.new || '') : '';
      }
      if (ch && typeof ch === 'object') return ch.message || '';
      return '';
    },
    avatarOf(item) {
      const uid = item.user_id;
      return uid === 1 || uid === null ? '管' : String(uid);
    },
    whoOf(item) {
      const uid = item.user_id;
      return uid === 1 ? '管理员' : (uid == null ? '系统' : '用户 ' + uid);
    },
    async loadM2o(relation) {
      if (!relation || this.m2oCache[relation]) return;
      try {
        const res = await ZCAPI.listRecords(relation, { limit: 500 });
        this.m2oCache[relation] = res.records.map((r) => ({ id: r.id, label: r._rec_name || '#' + r.id }));
      } catch (e) { this.m2oCache[relation] = []; }
    },
    m2oOptions(relation) { return this.m2oCache[relation] || []; },
    async init() {
      this.meta = await ZCAPI.describe(this.table);
      // many2one 选项预载
      for (const name of Object.keys(this.meta.fields)) {
        const f = this.meta.fields[name];
        if (f.type === 'many2one' && f.relation) this.loadM2o(f.relation);
      }
      if (this.isNew) {
        // 新建：selection/boolean 默认值
        this.form = {};
        for (const [name, f] of Object.entries(this.meta.fields)) {
          if (f.type === 'boolean') this.form[name] = f.default !== undefined ? f.default : false;
          if (f.options && f.options.length && f.default !== undefined) this.form[name] = f.default;
        }
      } else {
        await this.loadRecord();
      }
    },
    async loadRecord() {
      const res = await ZCAPI.getRecord(this.table, this.recordId);
      this.form = { ...res.record };
      this._recordData = res.record;
      this.chatter = res.chatter || [];
    },
    async save() {
      // 必填校验
      for (const [name, f] of Object.entries(this.meta.fields)) {
        if (f.required && !f.readonly && !f.system) {
          const v = this.form[name];
          if (v === undefined || v === null || v === '') {
            ElementPlus.ElMessage.warning('请填写【' + f.label + '】');
            return;
          }
        }
      }
      // 只提交表单里出现且非系统的字段
      const values = {};
      for (const group of this.groups) {
        for (const name of group.fields) {
          const f = this.meta.fields[name];
          if (f && f.system) continue;
          values[name] = this.form[name] === undefined ? null : this.form[name];
        }
      }
      this.saving = true;
      try {
        if (this.isNew) {
          const res = await ZCAPI.createRecord(this.table, values);
          ElementPlus.ElMessage.success('创建成功');
          this.$routerPush('/form/' + this.table + '/' + res.record.id);
        } else {
          const res = await ZCAPI.updateRecord(this.table, this.recordId, values);
          ElementPlus.ElMessage.success('保存成功');
          await this.loadRecord();
        }
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      } finally {
        this.saving = false;
      }
    },
    async onDelete() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '归档后该记录将从列表隐藏（数据保留，可恢复）。确定归档？',
          '归档确认', { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.deleteRecord(this.table, this.recordId);
        ElementPlus.ElMessage.success('已归档');
        this.$routerPush('/list/' + this.table);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '归档失败');
      }
    },
    async submitNote() {
      const body = (this.noteBody || '').trim();
      if (!body) return;
      this.noting = true;
      try {
        const res = await ZCAPI.addNote(this.table, this.recordId, body);
        this.chatter = res.chatter;
        this.noteBody = '';
        ElementPlus.ElMessage.success('已添加备注');
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '发送失败');
      } finally {
        this.noting = false;
      }
    },
  },
  mounted() { this.init(); },
  watch: {
    table() { this.init(); },
    recordId() { this.init(); },
  },
});
