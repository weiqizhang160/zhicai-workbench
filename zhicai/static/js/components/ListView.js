// 通用列表视图渲染器（项目书 8.2 ListView 规范，模型驱动 UI 的核心组件）
// 消费 meta API 的视图配置：字段、筛选器、搜索、排序、分页全部由配置驱动。
window.ListView = Vue.defineComponent({
  name: 'ListView',
  props: { table: { type: String, required: true } },
  template: `
  <div class="view-card">
    <!-- 工具栏 -->
    <div class="list-toolbar">
      <el-button type="primary" @click="onCreate" v-if="canCreate">
        <el-icon><plus></el-icon>&nbsp;新建
      </el-button>
      <el-button @click="exportCsv" :disabled="!records.length">导出 CSV</el-button>
      <div class="filter-chips" v-if="filters.length">
        <span class="filter-chip" v-for="f in filters" :key="f.label"
              :class="{active: activeFilter === f.label}" @click="toggleFilter(f)">
          {{ f.label }}
        </span>
      </div>
      <div class="spacer"></div>
      <el-input v-model="searchKw" placeholder="搜索…" clearable style="width: 220px"
                @keyup.enter="reload" @clear="reload" v-if="searchable.length">
        <template #prefix><el-icon><search></search></el-icon></template>
      </el-input>
      <el-button circle @click="reload" title="刷新">
        <el-icon><refresh></refresh></el-icon>
      </el-button>
    </div>

    <!-- 表格 -->
    <el-table :data="records" v-loading="loading" class="list-table"
              @sort-change="onSortChange" @row-click="onRowClick"
              style="width:100%" :default-sort="defaultSort">
      <el-table-column v-for="col in columns" :key="col.name"
                       :prop="col.name" :label="col.label" :sortable="'custom'"
                       :min-width="col.minWidth || 120">
        <template #default="{ row }">
          <template v-if="col.kind === 'selection'">
            <span class="zc-badge">
              <span class="dot" :style="{background: stateOf(col.name, row[col.name]).color}"></span>
              {{ stateOf(col.name, row[col.name]).label }}
            </span>
          </template>
          <template v-else-if="col.kind === 'boolean'">
            <el-tag v-if="row[col.name]" type="success" size="small">是</el-tag>
            <el-tag v-else type="info" size="small">否</el-tag>
          </template>
          <template v-else-if="col.kind === 'many2one'">
            <span v-if="row[col.name]">{{ nameOf(col.relation, row[col.name]) }}</span>
            <span v-else style="color: var(--zc-text-2)">—</span>
          </template>
          <span v-else>{{ row[col.name] === null || row[col.name] === '' ? '—' : row[col.name] }}</span>
        </template>
      </el-table-column>
      <el-table-column label="" width="80" prop="_open">
        <template #default>
          <span class="list-row-link">打开 ›</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空态 -->
    <div class="empty-state" v-if="!loading && !records.length">
      <div class="empty-icon">📋</div>
      <div>暂无数据</div>
    </div>

    <!-- 分页 -->
    <div class="pager-wrap">
      <el-pagination background layout="total, prev, pager, next" :total="total"
                     :page-size="limit" :current-page="page" @current-change="onPageChange">
      </el-pagination>
    </div>

    <!-- 新建客户向导（仅 res_book） -->
    <book-wizard v-if="table === 'res_book'" ref="wizard" @created="onBookCreated"></book-wizard>
  </div>
  `,
  data() {
    return {
      loading: false,
      meta: null,
      view: null,
      records: [],
      total: 0,
      page: 1,
      limit: 80,
      searchKw: '',
      activeFilter: null,
      sortField: null,
      sortOrder: null,
      nameCache: {},   // relation -> {id: label}
    };
  },
  computed: {
    columns() {
      if (!this.view) return [];
      const fields = this.meta.fields;
      return (this.view.fields || []).map((name) => {
        const f = fields[name] || {};
        let kind = f.type;
        if (f.type === 'selection' && f.options) kind = 'selection';
        if (f.type === 'many2one') kind = 'many2one';
        if (f.type === 'boolean') kind = 'boolean';
        return { name, label: f.label || name, kind, relation: f.relation };
      });
    },
    filters() { return (this.view && this.view.filters) || []; },
    searchable() { return (this.view && this.view.searchable) || []; },
    canCreate() { return this.meta && this.meta.table !== 'audit_log'; },
    defaultSort() {
      const o = this.view && this.view.default_order;
      if (!o) return {};
      const [field, dir] = o.split(' ');
      this.sortField = field; this.sortOrder = (dir || 'asc');
      return { prop: field, order: (dir === 'desc' ? 'descending' : 'ascending') };
    },
  },
  methods: {
    stateOf(kind, value) {
      return window.zcState(kind, value);
    },
    async loadNameCache(relation) {
      if (this.nameCache[relation]) return;
      try {
        const res = await ZCAPI.listRecords(relation, { limit: 500 });
        const map = {};
        res.records.forEach((r) => { map[r.id] = r._rec_name || ('#' + r.id); });
        this.nameCache[relation] = map;
      } catch (e) { this.nameCache[relation] = {}; }
    },
    nameOf(relation, id) {
      const m = this.nameCache[relation] || {};
      return m[id] || ('#' + id);
    },
    buildDomain() {
      const domain = [];
      // 筛选 chip
      if (this.activeFilter) {
        const f = this.filters.find((x) => x.label === this.activeFilter);
        if (f && f.domain) domain.push(...JSON.parse(JSON.stringify(f.domain)));
      }
      // 搜索：searchable 字段 ilike OR 组合
      const kw = (this.searchKw || '').trim();
      if (kw && this.searchable.length) {
        if (this.searchable.length === 1) {
          domain.push([this.searchable[0], 'ilike', kw]);
        } else {
          const orParts = ['|'];
          // 生成 N-1 个 | 前缀
          for (let i = 0; i < this.searchable.length - 2; i++) orParts.push('|');
          this.searchable.forEach((f) => orParts.push([f, 'ilike', kw]));
          domain.push(orParts);
        }
      }
      return domain;
    },
    async reload() {
      this.loading = true;
      try {
        const params = {
          domain: this.buildDomain(),
          limit: this.limit,
          offset: (this.page - 1) * this.limit,
        };
        if (this.sortField) {
          params.order = this.sortField + ' ' + (this.sortOrder || 'asc');
        }
        const res = await ZCAPI.listRecords(this.table, params);
        this.records = res.records;
        this.total = res.total;
        // many2one 名称缓存
        const relations = this.columns.filter((c) => c.kind === 'many2one' && c.relation)
          .map((c) => c.relation);
        for (const rel of relations) await this.loadNameCache(rel);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      } finally {
        this.loading = false;
      }
    },
    async init() {
      try {
        this.meta = await ZCAPI.describe(this.table);
        this.view = (this.meta.views && this.meta.views.list) || { fields: Object.keys(this.meta.fields).slice(0, 6) };
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载模型配置失败');
        return;
      }
      const o = this.view.default_order;
      if (o) { const [f, d] = o.split(' '); this.sortField = f; this.sortOrder = d || 'asc'; }
      await this.reload();
    },
    toggleFilter(f) {
      this.activeFilter = this.activeFilter === f.label ? null : f.label;
      this.page = 1;
      this.reload();
    },
    onSortChange({ prop, order }) {
      this.sortField = prop;
      this.sortOrder = order === 'descending' ? 'desc' : 'asc';
      this.reload();
    },
    onPageChange(p) { this.page = p; this.reload(); },
    onRowClick(row) {
      this.$routerPush('/form/' + this.table + '/' + row.id);
    },
    onCreate() {
      if (this.table === 'res_book') {
        // 客户新建走向导（项目书 7.3）
        this.$refs.wizard.open();
      } else {
        this.$routerPush('/new/' + this.table);
      }
    },
    onBookCreated() { this.reload(); },
    exportCsv() {
      const cols = this.columns;
      const header = cols.map((c) => c.label).join(',');
      const lines = this.records.map((r) => cols.map((c) => {
        let v = r[c.name];
        if (c.kind === 'selection') v = this.stateOf(c.name, v).label;
        if (c.kind === 'boolean') v = v ? '是' : '否';
        if (v === null || v === undefined) v = '';
        return '"' + String(v).replace(/"/g, '""') + '"';
      }).join(','));
      const blob = new Blob(['\ufeff' + header + '\n' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = this.table + '_export.csv';
      a.click();
      URL.revokeObjectURL(a.href);
    },
  },
  mounted() { this.init(); },
  watch: {
    table() { this.activeFilter = null; this.searchKw = ''; this.page = 1; this.init(); },
  },
});
