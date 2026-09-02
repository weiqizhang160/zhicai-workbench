/**
 * 前端渲染冒烟测试（jsdom）
 *
 * 用途：模拟真人操作——打开登录页 -> 输入账号密码 -> 点登录 -> 逐页点菜单，
 *       验证每个页面 .page-content 都真实渲染出内容（防白屏回归）。
 *
 * 运行：先启动服务，然后
 *   node tools/smoke.js
 * 依赖：jsdom（NODE_PATH 指向含 jsdom 的 node_modules）
 */
const { JSDOM, VirtualConsole } = require('jsdom');

const BASE = 'http://127.0.0.1:8000';
const results = [];
const errors = [];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -> ' + detail : ''}`);
}

(async () => {
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push('jsdomError: ' + (e.message || e)));
  vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

  // 会话 cookie 由页面内真实登录流程写入，更贴近用户实际操作
  let sessionCookie = '';

  const dom = await JSDOM.fromURL(`${BASE}/`, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      window.fetch = async function (input, init) {
        init = init || {};
        init.headers = Object.assign({}, init.headers || {});
        if (!(init.body instanceof window.FormData)) {
          init.headers['Content-Type'] = 'application/json';
        }
        if (sessionCookie) init.headers['Cookie'] = sessionCookie;
        const url = typeof input === 'string' ? new URL(input, BASE).href : input;
        const resp = await fetch(url, init);
        const sc = resp.headers.getSetCookie ? resp.headers.getSetCookie() : [];
        if (sc.length) sessionCookie = sc.map((c) => c.split(';')[0]).join('; ');
        return resp;
      };
    },
  });

  const { window } = dom;
  const doc = window.document;

  // ---------- 1. 首屏 ----------
  await wait(4000);
  const app = doc.getElementById('app');
  check('#app 已挂载', !!app);
  check('已脱离 boot-loading', !doc.querySelector('.boot-loading'),
    `app html len=${app ? app.innerHTML.length : 0}`);

  // ---------- 2. 登录页 ----------
  const inputs = doc.querySelectorAll('input');
  check('登录页渲染（账号+密码框）', inputs.length >= 2, `input 数量=${inputs.length}`);

  // jsdom 不实现 innerText，必须用 textContent
  const setValue = (el, v) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value'
    ).set;
    setter.call(el, v);
    el.dispatchEvent(new window.Event('input', { bubbles: true }));
  };
  setValue(inputs[0], 'admin');
  setValue(inputs[1], 'admin123');
  await wait(400);

  const allBtns = Array.from(doc.querySelectorAll('button'));
  const btn = allBtns.find((b) => /登\s*录/.test((b.textContent || '').trim()));
  check('找到登录按钮', !!btn,
    btn ? '' : '页面按钮=' + JSON.stringify(allBtns.map((b) => (b.textContent || '').trim())));

  if (btn) {
    btn.click();
    await wait(5000);
  }

  // ---------- 3. 登录后主界面 ----------
  const navs = doc.querySelectorAll('.nav-item');
  check('左侧菜单已渲染', navs.length > 0,
    `菜单项=[${Array.from(navs).slice(0, 8).map((n) => (n.textContent || '').trim()).join(', ')}]`);
  check('登录态生效（出现侧边栏）', !!doc.querySelector('.sidebar'));

  // —— 模板编译检查（防回归）——
  // 曾踩坑：v-model 绑定三元表达式（v-model="a ? b : c"）会触发 Vue 编译错误 42，
  // 导致整个组件白屏且控制台只有一行 URL 提示，极难定位。
  // 这里主动编译所有组件模板，把错误在冒烟阶段就暴露出来。
  const tplErrors = [];
  for (const name of ['MoveEntry', 'LedgerView', 'ReportView',
                      'InvoiceView', 'BankView', 'AutoEntryView',
                      'TaxDeclView',
                      'ContractView', 'TaskView',
                      'ForeignTradeView', 'PayrollView', 'DocumentsView',
                      'SettingsView',
                      'ListView', 'FormView', 'BookWizard']) {
    const comp = window[name];
    if (!comp || !comp.template) continue;
    try {
      window.Vue.compile(comp.template, {
        onError: (e) => tplErrors.push(
          `${name}: 第 ${e.loc && e.loc.start ? e.loc.start.line : '?'} 行 - ${e.message}`),
      });
    } catch (e) {
      tplErrors.push(`${name}: 编译抛异常 - ${e.message}`);
    }
  }
  check('所有组件模板编译无误', tplErrors.length === 0, tplErrors.join(' | '));

  const pageContent = () => doc.querySelector('.page-content');

  // ---------- 4. 逐页导航（防白屏回归） ----------
  const visit = async (label, hash, minLen) => {
    window.location.hash = hash;
    await wait(4000);
    const pc = pageContent();
    const len = pc ? pc.innerHTML.trim().length : -1;
    const title = doc.querySelector('.topbar-title');
    check(`${label} 渲染非空`, len > minLen,
      `len=${len} 标题=${title ? title.textContent.trim() : '?'}`);
    return pc ? pc.innerHTML : '';
  };

  const dashHtml = await visit('仪表盘', '#/', 500);
  const listHtml = await visit('客户列表', '#/list/res_book', 2000);
  const formHtml = await visit('客户表单', '#/form/res_book/1', 2000);
  await visit('会计科目列表', '#/list/account_account', 2000);
  await visit('往来单位列表', '#/list/res_partner', 500);

  // —— M2 记账核心定制页 ——
  const moveHtml = await visit('凭证录入', '#/move/new', 2000);
  const ledgerHtml = await visit('账簿查询', '#/ledger', 1000);
  const reportHtml = await visit('财务报表', '#/reports', 1000);
  await visit('凭证列表', '#/list/account_move', 500);

  // —— M3 票据 / 银行 / 自动记账 ——
  const invHtml = await visit('发票管理', '#/invoices', 1000);
  const bankHtml = await visit('银行对账', '#/bank', 1000);
  const aeHtml = await visit('自动记账工作台', '#/auto-entry', 1000);

  // —— M4 申报台账 ——
  const taxHtml = await visit('申报台账与日历', '#/tax-decl', 1000);
  check('申报台账页渲染（含日历/台账）',
    /申报台账|申报日历|批量生成台账|税种/.test(taxHtml), '');

  // —— M5 合同 / 任务 ——
  const contractHtml = await visit('合同与收费管理', '#/contracts', 1000);
  const taskHtml = await visit('任务看板', '#/tasks', 1000);
  check('合同页渲染（含列表/收款/报表 Tab）',
    /合同列表|收款登记|应收报表|新建合同/.test(contractHtml), '');
  check('任务看板页渲染（四列分栏）',
    /任务看板|待办|进行中|已完成|已取消/.test(taskHtml), '');

  // —— M6 外贸 / 工资 / 文档 ——
  const ftHtml = await visit('外贸专区', '#/foreign-trade', 1000);
  const payHtml = await visit('工资社保', '#/payroll', 1000);
  const docHtml = await visit('文档中心', '#/documents', 1000);
  check('外贸页渲染（含报关单/收汇/退税 Tab）',
    /报关单|收汇结汇|出口退税|平台链接/.test(ftHtml), '');
  check('工资页渲染（含批次/新建按钮）',
    /工资社保|新建工资批次|期间/.test(payHtml), '');
  check('文档中心渲染（含拖拽上传区）',
    /文档中心|拖到这里|全部客户/.test(docHtml), '');

  // —— M7 系统设置 ——
  const settingsHtml = await visit('系统设置', '#/settings', 1000);
  check('系统设置页渲染（含备份/任务/参数/审计 Tab）',
    /备份与恢复|计划任务|参数配置|审计日志/.test(settingsHtml), '');
  check('系统设置页含健康卡片与立即备份',
    /立即备份|数据库完整性|导出全量数据/.test(settingsHtml), '');

  check('发票管理页渲染（含导入入口）',
    /发票管理|导入|销项|进项/.test(invHtml), '');
  check('银行对账页渲染（含分栏）',
    /银行对账|流水|对账/.test(bankHtml), '');
  check('自动记账工作台渲染（含执行按钮）',
    /自动记账|批量执行|执行生成|命中规则/.test(aeHtml), '');

  check('各页内容互不相同（路由真的切换了）',
    dashHtml !== listHtml && listHtml !== formHtml && moveHtml !== ledgerHtml);
  check('凭证录入页含分录表格与合计栏',
    /move-total-bar|借方合计/.test(moveHtml), '');
  check('账簿查询页渲染（含期间筛选）', /期间|年度|科目余额表/.test(ledgerHtml), '');
  check('财务报表页渲染（含资产负债表）',
    /资产负债表|资产总计|利润表/.test(reportHtml), '');

  // 表单页关键校验：之前此处因 changes 类型错误白屏
  check('表单页含可编辑字段',
    /<input|<textarea|el-input|el-select/i.test(formHtml),
    `控件片段数=${(formHtml.match(/el-input|el-select|<input/g) || []).length}`);
  check('表单页含活动日志（chatter）',
    /chatter|活动|初始化/.test(formHtml));

  require('fs').writeFileSync('docs/smoke-form.html', formHtml || '<EMPTY>', 'utf8');
  require('fs').writeFileSync('docs/smoke-list.html', listHtml || '<EMPTY>', 'utf8');

  console.log('\n===== 控制台错误 =====');
  if (errors.length === 0) console.log('（无）');
  else errors.slice(0, 15).forEach((e) => console.log('  -', String(e).slice(0, 300)));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 汇总：${results.length - failed.length}/${results.length} 通过 =====`);
  dom.window.close();
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((e) => {
  console.error('冒烟测试异常：', e);
  process.exit(2);
});
