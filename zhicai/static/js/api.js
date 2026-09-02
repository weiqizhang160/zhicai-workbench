// API 封装：统一错误处理 + 会话过期拦截（项目书 8.3 交互规范）
window.ZCAPI = (function () {
  async function request(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      if (typeof FormData !== 'undefined' && body instanceof FormData) {
        // 文件上传：不要手动设 Content-Type，否则会丢掉 boundary 导致后端解析失败
        opts.body = body;
      } else {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
    }
    const resp = await fetch(url, opts);
    let data = null;
    try { data = await resp.json(); } catch (e) { /* 非 JSON 响应 */ }
    if (resp.status === 401 || (data && data.code === 'unauthorized')) {
      // 会话过期：踢回登录页
      if (window.ZC_APP_HOOKS && window.ZC_APP_HOOKS.onUnauthorized) {
        window.ZC_APP_HOOKS.onUnauthorized();
      }
      throw new Error(data && data.message ? data.message : '登录已过期');
    }
    if (!resp.ok) {
      const msg = data && data.message ? data.message : ('请求失败（' + resp.status + '）');
      const err = new Error(msg);
      err.code = data && data.code;
      throw err;
    }
    return data;
  }

  return {
    get: (url) => request('GET', url),
    post: (url, body) => request('POST', url, body),
    put: (url, body) => request('PUT', url, body),
    del: (url) => request('DELETE', url),

    // ---- 登录 ----
    login: (login, password) => request('POST', '/api/v1/auth/login', { login, password }),
    logout: () => request('POST', '/api/v1/auth/logout'),
    me: () => request('GET', '/api/v1/auth/me'),
    changePassword: (old_password, new_password) =>
      request('PUT', '/api/v1/auth/password', { old_password, new_password }),

    // ---- meta ----
    menus: () => request('GET', '/api/v1/meta/menu'),
    describe: (table) => request('GET', '/api/v1/meta/' + table),

    // ---- 通用 CRUD ----
    listRecords: (table, params) => {
      const qs = new URLSearchParams();
      if (params.domain) qs.set('domain', JSON.stringify(params.domain));
      if (params.limit) qs.set('limit', params.limit);
      if (params.offset) qs.set('offset', params.offset);
      if (params.order) qs.set('order', params.order);
      const s = qs.toString();
      return request('GET', '/api/v1/data/' + table + (s ? '?' + s : ''));
    },
    getRecord: (table, id) => request('GET', '/api/v1/data/' + table + '/' + id),
    createRecord: (table, values) => request('POST', '/api/v1/data/' + table, { values }),
    updateRecord: (table, id, values) => request('PUT', '/api/v1/data/' + table + '/' + id, { values }),
    deleteRecord: (table, id) => request('DELETE', '/api/v1/data/' + table + '/' + id),
    addNote: (table, id, body) => request('POST', '/api/v1/data/' + table + '/' + id + '/note', { body }),

    // ---- 业务动作 ----
    books: () => request('GET', '/api/v1/biz/books'),
    switchBook: (id) => request('PUT', '/api/v1/biz/books/' + id + '/switch'),
    createBook: (payload) => request('POST', '/api/v1/biz/books', payload),
    search: (q) => request('GET', '/api/v1/biz/search?q=' + encodeURIComponent(q)),

    // ---- M2 记账核心 ----
    acc: (function () {
      const A = '/api/v1/acc';
      const qs = (params) => {
        const s = new URLSearchParams();
        Object.keys(params || {}).forEach((k) => {
          if (params[k] !== null && params[k] !== undefined && params[k] !== '') s.set(k, params[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        // 凭证
        moves: (params) => request('GET', A + '/moves' + qs(params)),
        move: (id) => request('GET', A + '/moves/' + id),
        createMove: (body) => request('POST', A + '/moves', body),
        updateMove: (id, body) => request('PUT', A + '/moves/' + id, body),
        deleteMove: (id) => request('DELETE', A + '/moves/' + id),
        postMove: (id) => request('POST', A + '/moves/' + id + '/post'),
        bulkPost: (ids) => request('POST', A + '/moves/bulk-post', { ids }),
        reverseMove: (id, reverseDate) =>
          request('POST', A + '/moves/' + id + '/reverse', { reverse_date: reverseDate || null }),
        // 辅助数据
        journals: () => request('GET', A + '/journals'),
        leafAccounts: (kw) => request('GET', A + '/accounts/leaf' + qs({ kw })),
        partners: (kw) => request('GET', '/api/v1/data/res_partner' + qs({
          domain: kw ? [['name', 'ilike', kw]] : null, limit: 200,
        })),
        // 模板
        templates: () => request('GET', A + '/templates'),
        saveTemplate: (body) => request('POST', A + '/templates', body),
        // 期间
        periods: () => request('GET', A + '/periods'),
        closePeriod: (period, note) => request('POST', A + '/period/close', { period, note }),
        openPeriod: (period) => request('POST', A + '/period/open', { period }),
        // 结转
        carryForward: (period) => request('POST', A + '/carry-forward', { period }),
        // 账簿
        generalLedger: (p) => request('GET', A + '/ledger/general' + qs(p)),
        subsidiaryLedger: (p) => request('GET', A + '/ledger/subsidiary' + qs(p)),
        trialBalance: (p) => request('GET', A + '/ledger/trial' + qs(p)),
        // 报表
        balanceSheet: (period) => request('GET', A + '/report/balance-sheet' + qs({ period })),
        incomeStatement: (from, to) =>
          request('GET', A + '/report/income' + qs({ period_from: from, period_to: to })),
      };
    })(),

    // ---- M3 发票 / 银行 / 自动记账 ----
    inv: (function () {
      const B = '/api/v1/inv';
      const qs2 = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '') s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        bills: (p) => request('GET', B + '/bills' + qs2(p)),
        create: (body) => request('POST', B + '/bills', body),
        update: (id, body) => request('PUT', B + '/bills/' + id, body),
        remove: (id) => request('DELETE', B + '/bills/' + id),
        importPreview: (file) => {
          const fd = new FormData();
          fd.append('file', file);
          return request('POST', B + '/import-preview', fd);
        },
        importCommit: (rows) => request('POST', B + '/import-commit', { rows }),
        monthSummary: (period) => request('GET', B + '/month-summary' + qs2({ period })),
      };
    })(),

    bank: (function () {
      const B = '/api/v1/bank';
      const qs2 = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '') s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        lines: (p) => request('GET', B + '/lines' + qs2(p)),
        statements: () => request('GET', B + '/statements'),
        importPreview: (file, bankAlias, accountNo) => {
          const fd = new FormData();
          fd.append('file', file);
          let url = B + '/import-preview';
          const s = new URLSearchParams();
          if (bankAlias) s.set('bank_alias', bankAlias);
          if (accountNo) s.set('account_no', accountNo);
          if (s.toString()) url += '?' + s.toString();
          return request('POST', url, fd);
        },
        importCommit: (rows, bankAlias, accountNo) =>
          request('POST', B + '/import-commit',
                  { rows, bank_alias: bankAlias, account_no: accountNo }),
        linePreview: (id) => request('GET', B + '/lines/' + id + '/preview'),
        generateMove: (id, body) => request('POST', B + '/lines/' + id + '/generate-move', body || {}),
        monthSummary: (period) => request('GET', B + '/month-summary' + qs2({ period })),
      };
    })(),

    tax: (function () {
      const B = '/api/v1/tax';
      const qs2 = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '' && p[k] !== false) s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        items: (p) => request('GET', B + '/items' + qs2(p)),
        generate: (periods, bookIds) =>
          request('POST', B + '/generate', { periods, book_ids: bookIds || null }),
        compute: (id, overrides) =>
          request('POST', B + '/items/' + id + '/compute', { overrides: overrides || null }),
        snapshot: (id) => request('GET', B + '/items/' + id + '/snapshot'),
        submit: (id, amount, remark) =>
          request('POST', B + '/items/' + id + '/submit',
                  { declared_amount: amount, remark }),
        pay: (id, paidDate) => request('POST', B + '/items/' + id + '/pay', { paid_date: paidDate }),
        exempt: (id, reason, zero) =>
          request('POST', B + '/items/' + id + '/exempt', { reason, zero: !!zero }),
        setState: (id, state) => request('POST', B + '/items/' + id + '/state', { state }),
        calendar: (month) => request('GET', B + '/calendar' + qs2({ month })),
        links: () => request('GET', B + '/links'),
      };
    })(),

    ae: (function () {
      const B = '/api/v1/ae';
      return {
        rules: (trigger) => request('GET', B + '/rules' + (trigger ? '?trigger=' + trigger : '')),
        createRule: (body) => request('POST', B + '/rules', body),
        updateRule: (id, body) => request('PUT', B + '/rules/' + id, body),
        removeRule: (id) => request('DELETE', B + '/rules/' + id),
        pending: (period) => request('GET', B + '/pending' + (period ? '?period=' + period : '')),
        execute: (items) => request('POST', B + '/execute', { items }),
        logs: (result) => request('GET', B + '/logs' + (result ? '?result=' + result : '')),
      };
    })(),

    // ---- M5 合同 / 任务 / 仪表盘 ----
    contract: (function () {
      const B = '/api/v1/contract';
      const qs = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '' && p[k] !== false) s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        agreements: (p) => request('GET', B + '/agreements' + qs(p)),
        agreement: (id) => request('GET', B + '/agreements/' + id),
        createAgreement: (body) => request('POST', B + '/agreements', body),
        generateFee: (id) => request('POST', B + '/agreements/' + id + '/fee-items/generate'),
        feeItems: (p) => request('GET', B + '/fee-items' + qs(p)),
        bulkCollect: (ids, paidDate) =>
          request('POST', B + '/fee-items/bulk-collect',
                  { fee_item_ids: ids, paid_date: paidDate || null }),
        collect: (id, paidDate) =>
          request('POST', B + '/fee-items/' + id + '/collect', { paid_date: paidDate || null }),
        invoice: (id, invoiceNo) =>
          request('POST', B + '/fee-items/' + id + '/invoice', { invoice_no: invoiceNo || null }),
        receivable: (bookId) => request('GET', B + '/report/receivable' + qs({ book_id: bookId })),
        scan: () => request('POST', B + '/scan'),
      };
    })(),

    tasks: (function () {
      const B = '/api/v1/tasks';
      const qs = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '' && p[k] !== false) s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        list: (p) => request('GET', B + qs(p)),
        kanban: () => request('GET', B + '/kanban'),
        create: (body) => request('POST', B, body),
        update: (id, body) => request('PUT', B + '/' + id, body),
        setState: (id, state) => request('POST', B + '/' + id + '/state', { state }),
        remove: (id) => request('DELETE', B + '/' + id),
      };
    })(),

    dashboard: {
      summary: (month) => request('GET', '/api/v1/dashboard/summary' +
        (month ? '?month=' + encodeURIComponent(month) : '')),
    },

    // ---- M6 外贸专区 ----
    ft: (function () {
      const B = '/api/v1/ft';
      const qs = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '' && p[k] !== false) s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        decls: (p) => request('GET', B + '/decls' + qs(p)),
        decl: (id) => request('GET', B + '/decls/' + id),
        createDecl: (body) => request('POST', B + '/decls', body),
        removeDecl: (id) => request('DELETE', B + '/decls/' + id),
        importDecls: (bookId, rows) =>
          request('POST', B + '/decls/import-commit', { book_id: bookId, rows }),
        receipts: (p) => request('GET', B + '/fx-receipts' + qs(p)),
        createReceipt: (body) => request('POST', B + '/fx-receipts', body),
        removeReceipt: (id) => request('DELETE', B + '/fx-receipts/' + id),
        refunds: (p) => request('GET', B + '/refunds' + qs(p)),
        createRefund: (body) => request('POST', B + '/refunds', body),
        setRefundStatus: (id, status, receivedDate) =>
          request('POST', B + '/refunds/' + id + '/status',
                  { status, received_date: receivedDate || null }),
        platform: () => request('GET', B + '/platform'),
        savePlatformNotes: (notes) => request('PUT', B + '/platform/notes', { notes }),
        summary: () => request('GET', B + '/summary'),
      };
    })(),

    // ---- M6 工资社保 ----
    payroll: (function () {
      const B = '/api/v1/payroll';
      return {
        batches: (p) => {
          const s = new URLSearchParams();
          Object.keys(p || {}).forEach((k) => {
            if (p[k] !== null && p[k] !== undefined && p[k] !== '') s.set(k, p[k]);
          });
          const t = s.toString();
          return request('GET', B + '/batches' + (t ? '?' + t : ''));
        },
        batch: (id) => request('GET', B + '/batches/' + id),
        createBatch: (body) => request('POST', B + '/batches', body),
        addLine: (batchId, body) => request('POST', B + '/batches/' + batchId + '/lines', body),
        updateLine: (lineId, body) => request('PUT', B + '/lines/' + lineId, body),
        removeLine: (lineId) => request('DELETE', B + '/lines/' + lineId),
        recalc: (batchId) => request('POST', B + '/batches/' + batchId + '/recalc'),
        confirm: (batchId, moveDate) =>
          request('POST', B + '/batches/' + batchId + '/confirm',
                  moveDate ? { move_date: moveDate } : {}),
        markPaid: (batchId) => request('POST', B + '/batches/' + batchId + '/mark-paid'),
        iitPreview: (gross, socialEmployee) =>
          request('GET', B + '/iit/preview?gross=' + encodeURIComponent(gross) +
                  '&social_employee=' + encodeURIComponent(socialEmployee || '0')),
      };
    })(),

    // ---- M6 文档中心 ----
    docs: (function () {
      const B = '/api/v1/docs';
      const qs = (p) => {
        const s = new URLSearchParams();
        Object.keys(p || {}).forEach((k) => {
          if (p[k] !== null && p[k] !== undefined && p[k] !== '' && p[k] !== false) s.set(k, p[k]);
        });
        const t = s.toString();
        return t ? '?' + t : '';
      };
      return {
        list: (p) => request('GET', B + qs(p)),
        stats: () => request('GET', B + '/stats'),
        bySource: (model, id) => request('GET', B + '/by-source/' + model + '/' + id),
        get: (id) => request('GET', B + '/' + id),
        update: (id, values) => request('PUT', B + '/' + id, { values }),
        remove: (id) => request('DELETE', B + '/' + id),
        upload: (files, meta) => {
          const fd = new FormData();
          for (const f of files) fd.append('files', f);
          fd.append('book_id', meta.book_id);
          fd.append('doc_type', meta.doc_type || 'other');
          if (meta.tags) fd.append('tags', meta.tags);
          if (meta.doc_year) fd.append('doc_year', meta.doc_year);
          if (meta.name) fd.append('name', meta.name);
          if (meta.source_model) fd.append('source_model', meta.source_model);
          if (meta.source_id) fd.append('source_id', meta.source_id);
          if (meta.remark) fd.append('remark', meta.remark);
          return request('POST', B + '/upload', fd);
        },
      };
    })(),
    // ---- M7 运维 / 系统设置 ----
    mt: {
      backupRun: () => request('POST', '/api/v1/maintenance/backup/run'),
      backupLogs: () => request('GET', '/api/v1/maintenance/backup/logs'),
      backupFiles: () => request('GET', '/api/v1/maintenance/backup/files'),
      dbHealth: () => request('GET', '/api/v1/maintenance/db/health'),
      cron: () => request('GET', '/api/v1/maintenance/cron'),
      cronRun: (code) => request('POST', '/api/v1/maintenance/cron/' + code + '/run'),
      cronUpdate: (code, body) => request('PUT', '/api/v1/maintenance/cron/' + code, body),
      exportCsvUrl: '/api/v1/maintenance/export/csv',
    },
  };
})();
