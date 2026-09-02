// 主应用：AppShell（导航/顶栏/账套切换器/全局搜索）+ hash 路由 + 登录 + 仪表盘
// （项目书 7.1 / 8.1 布局规范）
(function () {
  const { createApp, reactive, ref, computed, watch, onMounted, defineComponent } = Vue;

  // ---------- 全局状态 ----------
  const store = reactive({
    me: null,            // 当前用户
    menus: [],           // 模块菜单
    books: [],           // 账套列表
    currentBookId: null, // null = 总览
    checking: true,      // 启动会话检查中
  });
  window.ZC_STORE = store;

  // 会话过期钩子（api.js 调用）
  window.ZC_APP_HOOKS = {
    onUnauthorized() {
      store.me = null;
      if (!location.hash.startsWith('#/login')) location.hash = '#/login';
    },
  };

  // ---------- hash 路由 ----------
  const route = reactive({ path: '/', table: null, id: null, mode: 'list' });
  const currentHash = ref('#/');   // 供菜单高亮判断（定制页用自定义 route，无 table 可比）

  function parseHash() {
    const h = (location.hash || '#/').slice(1);
    const parts = h.split('/').filter(Boolean);
    currentHash.value = location.hash || '#/';
    if (!parts.length) { Object.assign(route, { path: '/', table: null, id: null, mode: 'list' }); return; }
    if (parts[0] === 'login') { route.path = '/login'; return; }
    // —— M2 定制页路由 ——
    if (parts[0] === 'move') {
      // #/move/new        → 新建凭证
      // #/move/{id}       → 编辑凭证
      const id = parts[1] === 'new' || !parts[1] ? null : Number(parts[1]);
      Object.assign(route, { path: '/move', table: 'account_move', id, mode: id ? 'edit' : 'new' });
      return;
    }
    if (parts[0] === 'ledger') {
      Object.assign(route, { path: '/ledger', table: null, id: null, mode: 'ledger' });
      return;
    }
    if (parts[0] === 'reports') {
      Object.assign(route, { path: '/reports', table: null, id: null, mode: 'reports' });
      return;
    }
    // —— M3 定制页路由 ——
    if (parts[0] === 'invoices') {
      Object.assign(route, { path: '/invoices', table: 'invoice_bill', id: null, mode: 'invoices' });
      return;
    }
    if (parts[0] === 'bank') {
      Object.assign(route, { path: '/bank', table: 'bank_statement_line', id: null, mode: 'bank' });
      return;
    }
    if (parts[0] === 'auto-entry') {
      Object.assign(route, { path: '/auto-entry', table: 'auto_entry_rule', id: null,
                             mode: 'auto-entry' });
      return;
    }
    // —— M4 定制页路由 ——
    if (parts[0] === 'tax-decl') {
      Object.assign(route, { path: '/tax-decl', table: 'tax_decl_item', id: null,
                             mode: 'tax-decl' });
      return;
    }
    // —— M5 定制页路由 ——
    if (parts[0] === 'contracts') {
      Object.assign(route, { path: '/contracts', table: 'contract_agreement', id: null,
                             mode: 'contracts' });
      return;
    }
    if (parts[0] === 'tasks') {
      Object.assign(route, { path: '/tasks', table: 'task_task', id: null,
                             mode: 'tasks' });
      return;
    }
    // —— M6 定制页路由 ——
    if (parts[0] === 'foreign-trade') {
      Object.assign(route, { path: '/foreign-trade', table: null, id: null,
                             mode: 'foreign-trade' });
      return;
    }
    if (parts[0] === 'payroll') {
      Object.assign(route, { path: '/payroll', table: 'payroll_batch', id: null,
                             mode: 'payroll' });
      return;
    }
    if (parts[0] === 'documents') {
      Object.assign(route, { path: '/documents', table: 'doc_document', id: null,
                             mode: 'documents' });
      return;
    }
    // —— M7 定制页路由 ——
    if (parts[0] === 'settings') {
      Object.assign(route, { path: '/settings', table: null, id: null, mode: 'settings' });
      return;
    }
    if (parts[0] === 'list' && parts[1]) {
      Object.assign(route, { path: '/list', table: parts[1], id: null, mode: 'list' });
    } else if (parts[0] === 'form' && parts[1] && parts[2]) {
      Object.assign(route, { path: '/form', table: parts[1], id: Number(parts[2]), mode: 'form' });
    } else if (parts[0] === 'new' && parts[1]) {
      Object.assign(route, { path: '/form', table: parts[1], id: null, mode: 'form' });
    } else {
      Object.assign(route, { path: '/', table: null, id: null, mode: 'list' });
    }
  }
  window.addEventListener('hashchange', parseHash);

  function routerPush(path) {
    if (path.startsWith('/')) path = '#' + path;
    location.hash = path;
  }

  // 加载导航菜单与账套列表（登录后 / 会话恢复时调用；顶层定义，LoginView 与主应用共用）
  async function loadShellData() {
    try {
      const [menusRes, booksRes] = await Promise.all([ZCAPI.menus(), ZCAPI.books()]);
      store.menus = menusRes.menus;
      store.books = booksRes.books;
    } catch (e) {
      ElementPlus.ElMessage.error(e.message || '加载导航失败');
    }
  }

  // ---------- 登录组件 ----------
  const LoginView = defineComponent({
    template: `
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-logo">📊</div>
        <div class="login-title">智财代账工作台</div>
        <div class="login-sub">一人管百家账 · 本机部署 · 自动备份</div>
        <el-form label-position="top" @submit.prevent="doLogin">
          <el-form-item label="账号">
            <el-input v-model="login" placeholder="admin" size="large" autofocus>
              <template #prefix><el-icon><user></user></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="password" type="password" placeholder="初始密码 admin123" size="large"
                      show-password @keyup.enter="doLogin">
              <template #prefix><el-icon><lock></lock></el-icon></template>
            </el-input>
          </el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading"
                     @click="doLogin">登 录</el-button>
        </el-form>
        <div style="margin-top:14px;font-size:12px;color:var(--zc-text-2);text-align:center">
          首次登录后请在右上角用户菜单修改密码
        </div>
      </div>
    </div>`,
    data: () => ({ login: 'admin', password: '', loading: false }),
    methods: {
      async doLogin() {
        if (!this.login || !this.password) {
          ElementPlus.ElMessage.warning('请输入账号和密码');
          return;
        }
        this.loading = true;
        try {
          const res = await ZCAPI.login(this.login, this.password);
          store.me = res.user;
          await loadShellData();
          location.hash = '#/';
          ElementPlus.ElMessage.success('欢迎回来，' + res.user.name);
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '登录失败');
        } finally {
          this.loading = false;
        }
      },
    },
  });

  // ---------- 仪表盘（项目书 7.2：六张卡片，跨账套聚合，可点击穿透） ----------
  const DashboardView = defineComponent({
    data() {
      const d = new Date();
      return {
        month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
        summary: null,
        loading: false,
      };
    },
    computed: {
      monthOptions() {
        const y = new Date().getFullYear();
        return Array.from({ length: 12 }, (_, i) => ({
          value: `${y}-${String(i + 1).padStart(2, '0')}`, label: `${i + 1} 月`,
        }));
      },
    },
    mounted() { this.load(); },
    methods: {
      fmt(v) {
        const n = parseFloat(v) || 0;
        return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      },
      kindLabel(k) {
        return ({ vat: '增值税', surtax: '附加税', cit_quarterly: '所得税(季)',
                  cit_annual: '所得税(年报)', iit: '个税', stamp: '印花税' })[k] || k;
      },
      async load() {
        this.loading = true;
        try {
          const r = await ZCAPI.dashboard.summary(this.month);
          this.summary = r;
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '仪表盘加载失败');
          this.summary = null;
        }
        this.loading = false;
      },
      go(path) { location.hash = path; },
      goBook(b) { location.hash = '#/form/res_book/' + b.book_id; },
      lightClass(light) { return { none: 'lamp-none', done: 'lamp-done', pending: 'lamp-pending' }[light] || 'lamp-none'; },
    },
    template: `
    <div v-loading="loading">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
        <div style="font-size:13px; color:var(--zc-text-2)">
          首页工作台 · 跨账套总览，点击卡片可穿透到对应明细
        </div>
        <el-select v-model="month" size="small" style="width:110px" @change="load">
          <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
        </el-select>
      </div>

      <div class="dash-grid" v-if="summary">
        <!-- 1. 本月概览 -->
        <div class="dash-card">
          <h4>本月概览</h4>
          <div class="dash-big">{{ summary.overview.normal_books }}</div>
          <div class="dash-row"><span>服务客户（含暂停共 {{ summary.overview.total_books }}）</span></div>
          <div class="dash-row" @click="go('#/list/account_move')">
            <span>待过账凭证</span><span class="hl-warn">{{ summary.overview.draft_moves }}</span>
          </div>
          <div class="dash-row" @click="go('#/list/account_move')">
            <span>已过账凭证</span><span class="hl-ok">{{ summary.overview.posted_moves }}</span>
          </div>
          <div class="dash-row" @click="go('#/invoices')">
            <span>本月新发票</span><span>{{ summary.overview.new_invoices }}</span>
          </div>
        </div>

        <!-- 2. 申报日历红牌 -->
        <div class="dash-card" @click="go('#/tax-decl')">
          <h4>申报日历红牌（未来 7 天）</h4>
          <div v-if="!summary.decl_alert.length" class="dash-empty">未来 7 天无到期申报</div>
          <div v-else class="dash-list">
            <div class="dash-row" v-for="it in summary.decl_alert.slice(0, 6)" :key="it.id">
              <span>{{ it.book_name }} · {{ kindLabel(it.tax_kind) }}</span>
              <span class="hl-warn">{{ it.due_date }}</span>
            </div>
          </div>
        </div>

        <!-- 3. 逾期预警 -->
        <div class="dash-card">
          <h4>逾期预警</h4>
          <div class="dash-row" @click="go('#/tax-decl')">
            <span>逾期未申报</span><span class="hl-danger">{{ summary.overdue.decl }}</span>
          </div>
          <div class="dash-row" @click="go('#/contracts')">
            <span>逾期未收代账费</span><span class="hl-danger">{{ summary.overdue.fee }}</span>
          </div>
        </div>

        <!-- 4. 待办任务 -->
        <div class="dash-card" @click="go('#/tasks')">
          <h4>待办任务</h4>
          <div v-if="!summary.todo_tasks.length" class="dash-empty">暂无待办</div>
          <div v-else class="dash-list">
            <div class="dash-row" v-for="t in summary.todo_tasks.slice(0, 10)" :key="t.id">
              <span class="ellipsis" :title="t.title">{{ t.title }}</span>
              <span>{{ t.due_date || '—' }}</span>
            </div>
          </div>
        </div>

        <!-- 5. 收款月历 -->
        <div class="dash-card" @click="go('#/contracts')">
          <h4>本月收款（代账费）</h4>
          <div class="dash-big" style="font-size:24px">¥{{ fmt(summary.fee_month.received) }}</div>
          <div class="dash-row"><span>本月应收</span><span>¥{{ fmt(summary.fee_month.receivable) }}</span></div>
          <div class="dash-row"><span>已收</span><span class="hl-ok">¥{{ fmt(summary.fee_month.received) }}</span></div>
          <div class="dash-row"><span>未收</span><span class="hl-warn">¥{{ fmt(summary.fee_month.unpaid) }}</span></div>
        </div>

        <!-- 6. 各客户进度 -->
        <div class="dash-card dash-card-wide">
          <h4>各客户进度（本月）</h4>
          <div class="progress-head">
            <span class="ph-name">客户</span>
            <span>收票</span><span>凭证</span><span>申报</span><span>收费</span>
          </div>
          <div class="progress-body">
            <div class="progress-row" v-for="p in summary.progress" :key="p.book_id" @click="goBook(p)">
              <span class="ph-name ellipsis" :title="p.code + ' ' + p.short_name">
                {{ p.code }} {{ p.short_name }}
              </span>
              <span><i class="lamp" :class="lightClass(p.invoice.light)"></i>{{ p.invoice.count || '' }}</span>
              <span><i class="lamp" :class="lightClass(p.move.light)"></i>{{ p.move.posted || '' }}</span>
              <span><i class="lamp" :class="lightClass(p.decl.light)"></i>{{ p.decl.done }}/{{ p.decl.total }}</span>
              <span><i class="lamp" :class="lightClass(p.fee.light)"></i>{{ p.fee.done }}/{{ p.fee.total }}</span>
            </div>
          </div>
          <div class="dash-legend">
            <span><i class="lamp lamp-done"></i>完成</span>
            <span><i class="lamp lamp-pending"></i>进行中/未完成</span>
            <span><i class="lamp lamp-none"></i>本月无此项</span>
          </div>
        </div>
      </div>
      <div v-else class="dash-empty" style="height:200px">暂无数据</div>
    </div>`,
  });

  // ---------- 主应用 ----------
  const app = createApp({
    setup() {
      const sidebarCollapsed = ref(false);
      const searchKw = ref('');
      const searchResults = ref([]);
      const showSearchPop = ref(false);
      const passwordDialog = ref(false);
      const pwForm = reactive({ old_password: '', new_password: '', confirm: '' });

      const menuGroups = computed(() => {
        const groups = [];
        const map = {};
        for (const m of store.menus) {
          const g = m.group || '其他';
          if (!map[g]) { map[g] = { label: g, items: [] }; groups.push(map[g]); }
          map[g].items.push(m);
        }
        // 工作台固定在第一组
        return groups;
      });

      const currentTitle = computed(() => {
        if (route.path === '/') return '工作台';
        if (route.path === '/login') return '登录';
        // —— M2 定制页（无 table，按 path 取标题） ——
        if (route.path === '/move') return route.id ? '编辑凭证' : '凭证录入';
        if (route.path === '/ledger') return '账簿查询';
        if (route.path === '/reports') return '财务报表';
        if (route.path === '/invoices') return '发票管理';
        if (route.path === '/bank') return '银行对账';
        if (route.path === '/auto-entry') return '自动记账 · 批量执行';
        if (route.path === '/tax-decl') return '申报台账与日历';
        // —— M5 ——
        if (route.path === '/contracts') return '合同与收费管理';
        if (route.path === '/tasks') return '任务看板';
        // —— M6 ——
        if (route.path === '/foreign-trade') return '外贸专区';
        if (route.path === '/payroll') return '工资社保';
        if (route.path === '/documents') return '文档中心';
        // —— M7 ——
        if (route.path === '/settings') return '系统设置';
        if (route.table) {
          const item = store.menus.find((m) => m.table === route.table);
          return (item && item.label) || route.table;
        }
        return '智财代账工作台';
      });

      async function initSession() {
        try {
          const res = await ZCAPI.me();
          store.me = res.user;
          if (store.me) {
            await loadShellData();
            // 读当前账套 cookie
            const m = document.cookie.match(/zhicai_book=(\d+)/);
            store.currentBookId = m ? Number(m[1]) : null;
            if (location.hash.startsWith('#/login')) location.hash = '#/';
          } else if (!location.hash || location.hash === '#/') {
            location.hash = '#/login';
          }
        } finally {
          store.checking = false;
        }
      }

      async function switchBook(val) {
        try {
          await ZCAPI.switchBook(val || 0);
          store.currentBookId = val || null;
          // 重新加载当前视图数据：简单可靠的方式是重挂组件（改 key）
          route._ts = Date.now();
          ElementPlus.ElMessage.success(
            val ? '已切换到【' + (store.books.find((b) => b.id === val) || {}).short_name + '】'
                : '已切换到总览模式');
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '切换失败');
        }
      }

      async function doSearch(kw) {
        if (!kw || !kw.trim()) { searchResults.value = []; return; }
        try {
          const res = await ZCAPI.search(kw.trim());
          searchResults.value = res.results;
          showSearchPop.value = true;
        } catch (e) { searchResults.value = []; }
      }

      let searchTimer = null;
      watch(searchKw, (kw) => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => doSearch(kw), 300);
      });

      async function doLogout() {
        try {
          await ZCAPI.logout();
          store.me = null;
          location.hash = '#/login';
        } catch (e) { /* 忽略 */ }
      }

      async function changePassword() {
        if (!pwForm.old_password || !pwForm.new_password) {
          ElementPlus.ElMessage.warning('请填写完整');
          return;
        }
        if (pwForm.new_password !== pwForm.confirm) {
          ElementPlus.ElMessage.warning('两次新密码不一致');
          return;
        }
        try {
          await ZCAPI.changePassword(pwForm.old_password, pwForm.new_password);
          ElementPlus.ElMessage.success('密码已修改');
          passwordDialog.value = false;
          pwForm.old_password = pwForm.new_password = pwForm.confirm = '';
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '修改失败');
        }
      }

      function iconComp(name) {
        return (ElementPlusIconsVue && ElementPlusIconsVue[name]) || ElementPlusIconsVue.Document;
      }

      // 菜单跳转：定制页用后端声明的 route（如 #/move/new），其余走通用列表页
      function goMenu(m) {
        if (m.route) {
          if (location.hash === m.route) {
            // 已在当前页：强制重建组件（"凭证录入"重复点击应重置为一张空凭证）
            route._ts = Date.now();
            parseHash();
          } else {
            location.hash = m.route;
          }
        } else {
          routerPush('/list/' + m.table);
        }
      }

      const currentView = computed(() => {
        if (!store.me) return LoginView;
        if (route.path === '/' || route.path === '/login') return DashboardView;
        if (route.path === '/list') return 'list-view';
        if (route.path === '/form') {
          // 凭证走定制录入页（项目书 7.5：凭证录入是定制页，不用通用 FormView）
          if (route.table === 'account_move') return 'move-entry';
          return 'form-view';
        }
        // —— M2 定制页 ——
        if (route.path === '/move') return 'move-entry';
        if (route.path === '/ledger') return 'ledger-view';
        if (route.path === '/reports') return 'report-view';
        // —— M3 ——
        if (route.path === '/invoices') return 'invoice-view';
        if (route.path === '/bank') return 'bank-view';
        if (route.path === '/auto-entry') return 'auto-entry-view';
        // —— M4 ——
        if (route.path === '/tax-decl') return 'tax-decl-view';
        // —— M5 ——
        if (route.path === '/contracts') return 'contract-view';
        if (route.path === '/tasks') return 'task-view';
        // —— M6 ——
        if (route.path === '/foreign-trade') return 'foreign-trade-view';
        if (route.path === '/payroll') return 'payroll-view';
        if (route.path === '/documents') return 'documents-view';
        // —— M7 ——
        if (route.path === '/settings') return 'settings-view';
        return DashboardView;
      });
      const viewKey = computed(() => {
        // 必须含 path：/move/new 与 /move/1 是不同的编辑目标，否则组件不重建
        return [route.path, route.table, route.id, store.currentBookId, route._ts].join('-');
      });

      onMounted(() => {
        parseHash();
        initSession();
      });

      return {
        store, route, currentHash, sidebarCollapsed, currentTitle, menuGroups,
        searchKw, searchResults, showSearchPop,
        passwordDialog, pwForm,
        currentView, viewKey,
        switchBook, doSearch, doLogout, changePassword, iconComp, routerPush, goMenu,
      };
    },
    template: `
    <div style="height: 100%">
      <!-- 会话检查中 -->
      <div class="boot-loading" v-if="store.checking">
        <div class="boot-spinner"></div>
        <div>正在进入智财代账工作台…</div>
      </div>

      <!-- 登录页 -->
      <login-view v-else-if="!store.me"></login-view>

      <!-- 主框架 AppShell -->
      <div class="shell" v-else>
        <!-- 左侧导航（模块注册表驱动） -->
        <aside class="sidebar" :class="{collapsed: sidebarCollapsed}">
          <div class="sidebar-logo">
            <span class="logo-icon">📊</span>
            <span class="logo-text">智财代账工作台</span>
          </div>
          <nav class="sidebar-nav">
            <template v-for="group in menuGroups" :key="group.label">
              <div class="nav-group-title">{{ group.label }}</div>
              <div class="nav-item" v-for="m in group.items" :key="m.key"
                   :class="{active: m.route ? (currentHash === m.route) : (route.table === m.table)}"
                   @click="goMenu(m)" :title="m.label">
                <el-icon class="nav-icon"><component :is="iconComp(m.icon)"></component></el-icon>
                <span class="nav-label">{{ m.label }}</span>
              </div>
            </template>
          </nav>
          <div style="padding: 10px; cursor: pointer; color: rgba(255,255,255,0.6)"
               @click="sidebarCollapsed = !sidebarCollapsed">
            <el-icon><arrow-left v-if="!sidebarCollapsed"></arrow-left><arrow-right v-else></arrow-right></el-icon>
          </div>
        </aside>

        <div class="main-area">
          <!-- 顶栏 -->
          <header class="topbar">
            <div class="topbar-title">{{ currentTitle }}</div>
            <div class="topbar-spacer"></div>
            <!-- 全局搜索 -->
            <el-popover v-model:visible="showSearchPop" placement="bottom-end" :width="340" trigger="manual">
              <template #reference>
                <el-input v-model="searchKw" placeholder="搜索客户 / 科目…" clearable
                          class="global-search" @focus="showSearchPop = !!searchResults.length">
                  <template #prefix><el-icon><search></search></el-icon></template>
                </el-input>
              </template>
              <div class="search-pop">
                <div class="search-item" v-for="r in searchResults" :key="r.type + r.id"
                     @click="routerPush(r.route); showSearchPop = false">
                  <div class="title">{{ r.title }}</div>
                  <div class="subtitle">{{ r.subtitle }}</div>
                </div>
                <div v-if="!searchResults.length" style="padding: 12px; color: var(--zc-text-2); font-size: 13px">
                  没有匹配结果
                </div>
              </div>
            </el-popover>
            <!-- 账套切换器 -->
            <el-select class="book-switcher" :model-value="store.currentBookId"
                       placeholder="总览（全部客户）" filterable clearable
                       @change="switchBook" size="default">
              <el-option :value="null" label="🏢 总览（全部客户）"></el-option>
              <el-option v-for="b in store.books" :key="b.id" :value="b.id"
                         :label="b.code + ' ' + b.short_name">
                <span>{{ b.code }} {{ b.short_name }}</span>
                <span style="float:right;color:var(--zc-text-2);font-size:12px"
                      v-if="b.charge_status === 'paused'">暂停</span>
              </el-option>
            </el-select>
            <!-- 用户菜单 -->
            <el-dropdown @command="(cmd) => cmd === 'logout' ? doLogout() : (passwordDialog = true)">
              <el-button circle>
                <span style="font-weight:600">{{ (store.me.name || '?')[0] }}</span>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item disabled>
                    {{ store.me.name }}（{{ store.me.role_name }}）
                  </el-dropdown-item>
                  <el-dropdown-item divided command="password">
                    <el-icon><key></el-icon>&nbsp;修改密码
                  </el-dropdown-item>
                  <el-dropdown-item command="logout">
                    <el-icon><switch-button></switch-button></el-icon>&nbsp;退出登录
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </header>

          <!-- 主内容区 -->
          <main class="page-content">
            <component :is="currentView" :key="viewKey"
                       :table="route.table" :record-id="route.id" :mode="route.mode"></component>
          </main>
        </div>
      </div>

      <!-- 修改密码弹窗 -->
      <el-dialog v-model="passwordDialog" title="修改密码" width="420px">
        <el-form label-position="top">
          <el-form-item label="原密码">
            <el-input v-model="pwForm.old_password" type="password" show-password></el-input>
          </el-form-item>
          <el-form-item label="新密码（至少 6 位）">
            <el-input v-model="pwForm.new_password" type="password" show-password></el-input>
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="pwForm.confirm" type="password" show-password></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="passwordDialog = false">取消</el-button>
          <el-button type="primary" @click="changePassword">确认修改</el-button>
        </template>
      </el-dialog>
    </div>
    `,
  });

  // ---------- 装配 ----------
  const { ElMessage, ElMessageBox } = ElementPlus;
  const zhLocale = window.ElementPlusLocaleZhCn ? window.ElementPlusLocaleZhCn.default || window.ElementPlusLocaleZhCn : undefined;
  app.use(ElementPlus, { locale: zhLocale });
  for (const [name, comp] of Object.entries(ElementPlusIconsVue)) {
    app.component(name, comp);
  }
  app.component('login-view', LoginView);
  app.component('list-view', window.ListView);
  app.component('form-view', window.FormView);
  app.component('book-wizard', window.BookWizard);
  // —— M2 记账核心定制页 ——
  app.component('move-entry', window.MoveEntry);
  app.component('ledger-view', window.LedgerView);
  app.component('report-view', window.ReportView);
  // —— M3 票据 / 银行 / 自动记账 ——
  app.component('invoice-view', window.InvoiceView);
  app.component('bank-view', window.BankView);
  app.component('auto-entry-view', window.AutoEntryView);
  // —— M4 税务申报 ——
  app.component('tax-decl-view', window.TaxDeclView);
  // —— M5 合同 / 任务 ——
  app.component('contract-view', window.ContractView);
  app.component('task-view', window.TaskView);
  // —— M6 外贸 / 工资 / 文档 ——
  app.component('foreign-trade-view', window.ForeignTradeView);
  app.component('payroll-view', window.PayrollView);
  app.component('documents-view', window.DocumentsView);
  // —— M7 系统设置 ——
  app.component('settings-view', window.SettingsView);
  app.config.globalProperties.$routerPush = routerPush;
  app.config.globalProperties.$message = ElMessage;
  app.mount('#app');
})();
