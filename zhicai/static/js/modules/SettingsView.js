// 系统设置页（M7，项目书 7.13/7.14）：备份与恢复 / 计划任务 / 参数配置 / 审计日志
(function () {
  const { defineComponent } = Vue;

  window.SettingsView = defineComponent({
    data() {
      return {
        tab: 'backup',
        loading: false,

        // —— 备份与恢复 ——
        health: null,
        backupLogs: [],
        backupFiles: [],
        backupRunning: false,
        showRestoreGuide: false,

        // —— 计划任务 ——
        cron: null,
        timeDialog: false,
        timeForm: { code: '', name: '', daily_time: '' },
        cronRunning: '',

        // —— 参数配置 ——
        cfgKw: '',
        cfgs: [],
        cfgDialog: false,
        cfgForm: { id: null, key: '', value: '', remark: '' },

        // —— 审计日志 ——
        users: [],
        auditFilters: { model: '', user_id: null, date_from: '', date_to: '' },
        audits: [],
        auditTotal: 0,
      };
    },

    computed: {
      filteredCfgs() {
        const kw = (this.cfgKw || '').trim().toLowerCase();
        if (!kw) return this.cfgs;
        return this.cfgs.filter((c) =>
          (c.key || '').toLowerCase().includes(kw) ||
          (c.remark || '').toLowerCase().includes(kw));
      },
      userName() {
        const map = {};
        this.users.forEach((u) => { map[u.id] = u.name; });
        return (id) => map[id] || (id ? '#' + id : '系统');
      },
    },

    mounted() {
      this.loadBackupTab();
      this.loadCron();
      this.loadCfgs();
      this.loadUsers();
    },

    methods: {
      fmtSize(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1024 / 1024).toFixed(2) + ' MB';
      },
      fmtMs(n) {
        n = Number(n) || 0;
        return n < 1000 ? n + ' ms' : (n / 1000).toFixed(1) + ' s';
      },
      statusTag(s) {
        return { ok: 'success', skipped: 'info', failed: 'danger', fail: 'danger' }[s] || 'info';
      },
      statusLabel(s) {
        return { ok: '成功', skipped: '跳过', failed: '失败', fail: '失败' }[s] || (s || '—');
      },
      triggerLabel(t) {
        return { startup: '启动补跑', timer: '定时', manual: '手动' }[t] || t;
      },

      // ==================== 备份与恢复 ====================
      async loadBackupTab() {
        this.loading = true;
        try {
          const [h, logs, files] = await Promise.all([
            ZCAPI.mt.dbHealth(), ZCAPI.mt.backupLogs(), ZCAPI.mt.backupFiles(),
          ]);
          this.health = h;
          this.backupLogs = logs.items;
          this.backupFiles = files.items;
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '加载备份信息失败');
        }
        this.loading = false;
      },
      async runBackup() {
        this.backupRunning = true;
        try {
          const r = await ZCAPI.mt.backupRun();
          ElementPlus.ElMessage.success('备份完成：' + (r.result.file_name || '已记录日志'));
          await this.loadBackupTab();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '备份失败');
        }
        this.backupRunning = false;
      },
      exportCsv() {
        window.open(ZCAPI.mt.exportCsvUrl);
        ElementPlus.ElMessage.success('正在打包全量数据，稍后开始下载');
      },

      // ==================== 计划任务 ====================
      async loadCron() {
        try {
          this.cron = await ZCAPI.mt.cron();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '加载计划任务失败');
        }
      },
      async runCron(job) {
        this.cronRunning = job.code;
        try {
          await ZCAPI.mt.cronRun(job.code);
          ElementPlus.ElMessage.success('「' + job.name + '」已执行');
          await this.loadCron();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '执行失败');
        }
        this.cronRunning = '';
      },
      async toggleCron(job) {
        try {
          await ZCAPI.mt.cronUpdate(job.code, { active: !job.active });
          ElementPlus.ElMessage.success(job.active ? '已停用' : '已启用');
          await this.loadCron();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '操作失败');
        }
      },
      editTime(job) {
        this.timeForm = { code: job.code, name: job.name, daily_time: job.daily_time };
        this.timeDialog = true;
      },
      async saveTime() {
        if (!/^\d{1,2}:\d{1,2}$/.test(this.timeForm.daily_time)) {
          ElementPlus.ElMessage.warning('时间格式应为 HH:MM');
          return;
        }
        try {
          await ZCAPI.mt.cronUpdate(this.timeForm.code, { daily_time: this.timeForm.daily_time });
          ElementPlus.ElMessage.success('已保存');
          this.timeDialog = false;
          await this.loadCron();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '保存失败');
        }
      },

      // ==================== 参数配置 ====================
      async loadCfgs() {
        try {
          const r = await ZCAPI.listRecords('ir_config', { limit: 500, order: 'key' });
          this.cfgs = r.records;
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '加载参数失败');
        }
      },
      editCfg(c) {
        this.cfgForm = {
          id: c.id, key: c.key,
          value: c.value === null || c.value === undefined ? '' : String(c.value),
          remark: c.remark || '',
        };
        this.cfgDialog = true;
      },
      async saveCfg() {
        try {
          await ZCAPI.updateRecord('ir_config', this.cfgForm.id, {
            value: this.cfgForm.value, remark: this.cfgForm.remark,
          });
          ElementPlus.ElMessage.success('参数已保存，下次计算即生效');
          this.cfgDialog = false;
          await this.loadCfgs();
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '保存失败');
        }
      },

      // ==================== 审计日志 ====================
      async loadUsers() {
        try {
          const r = await ZCAPI.listRecords('res_users', { limit: 100 });
          this.users = r.records;
        } catch (e) { /* 非关键 */ }
      },
      async searchAudits() {
        const f = this.auditFilters;
        const domain = [];
        if (f.model && f.model.trim()) domain.push(['model', 'ilike', f.model.trim()]);
        if (f.user_id) domain.push(['user_id', '=', f.user_id]);
        if (f.date_from) domain.push(['created_at', '>=', f.date_from + 'T00:00:00']);
        if (f.date_to) domain.push(['created_at', '<=', f.date_to + 'T23:59:59']);
        this.loading = true;
        try {
          const r = await ZCAPI.listRecords('audit_log', {
            domain: domain.length ? domain : null,
            limit: 300, order: 'id desc',
          });
          this.audits = r.records;
          this.auditTotal = r.total || r.records.length;
        } catch (e) {
          ElementPlus.ElMessage.error(e.message || '查询审计日志失败');
        }
        this.loading = false;
      },
      shortChanges(c) {
        if (!c) return '';
        try {
          const obj = JSON.parse(c);
          return Object.keys(obj).slice(0, 4).join('、') +
            (Object.keys(obj).length > 4 ? ' 等' + Object.keys(obj).length + ' 项' : '');
        } catch (e) {
          return (c || '').slice(0, 60);
        }
      },
    },

    template: `
    <div v-loading="loading" style="max-width:1200px">
      <el-tabs v-model="tab">

        <!-- ============ Tab 1：备份与恢复 ============ -->
        <el-tab-pane label="备份与恢复" name="backup">
          <div class="stat-grid" v-if="health" style="margin-bottom:14px">
            <div class="stat-item">
              <div class="stat-label">数据库完整性</div>
              <div class="stat-value" :style="{color: health.ok ? '#67c23a' : '#f56c6c'}">
                {{ health.ok ? '正常' : '异常' }}
              </div>
              <div class="stat-sub">{{ health.journal_mode }} 模式</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">数据库大小</div>
              <div class="stat-value">{{ fmtSize(health.db_size) }}</div>
              <div class="stat-sub">WAL {{ fmtSize(health.wal_size) }}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">现有备份</div>
              <div class="stat-value">{{ health.backups_kept }} 份</div>
              <div class="stat-sub ellipsis" :title="health.db_path">{{ health.db_path }}</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">空闲页</div>
              <div class="stat-value">{{ health.freelist_count }}</div>
              <div class="stat-sub">页总数 {{ health.page_count }}</div>
            </div>
          </div>

          <div style="display:flex; gap:10px; margin-bottom:14px">
            <el-button type="primary" :loading="backupRunning" @click="runBackup">
              <el-icon style="margin-right:4px"><refresh-right></refresh-right></el-icon>立即备份
            </el-button>
            <el-button @click="exportCsv">
              <el-icon style="margin-right:4px"><download></download></el-icon>导出全量数据（CSV 包）
            </el-button>
            <el-button text type="primary" @click="showRestoreGuide = !showRestoreGuide">
              {{ showRestoreGuide ? '收起' : '查看' }}从备份恢复的步骤
            </el-button>
          </div>

          <el-collapse-transition>
            <el-alert v-if="showRestoreGuide" type="warning" :closable="false" style="margin-bottom:14px">
              <template #title>从备份恢复（说明式引导，系统不自动覆盖，请按步骤操作）</template>
              <div style="line-height:1.9; font-size:13px">
                1. 关闭正在运行的系统（关掉 start.bat 启动的黑窗口）；<br>
                2. 找到备份文件：打开备份目录「OneDrive/zhicai_backup/」，选择要恢复的 zhicai_日期_时间.db；<br>
                3. 把当前 data/zhicai.db 改名为 zhicai.db.bak（留一手）；<br>
                4. 把选中的备份文件复制到 data/ 目录，改名为 zhicai.db；<br>
                5. 双击 start.bat 重新启动，登录后到「工作台」核对客户数量和最近凭证；<br>
                6. 确认无误后可删除 zhicai.db.bak；有问题就换回它再启动。
              </div>
            </el-alert>
          </el-collapse-transition>

          <h4 style="margin:16px 0 8px">备份历史</h4>
          <el-table :data="backupLogs" size="small" border max-height="360">
            <el-table-column label="时间" width="160">
              <template #default="{row}">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
            </el-table-column>
            <el-table-column prop="file_name" label="文件" min-width="180" show-overflow-tooltip></el-table-column>
            <el-table-column label="大小" width="90">
              <template #default="{row}">{{ fmtSize(row.file_size) }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{row}">{{ fmtMs(row.duration_ms) }}</template>
            </el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{row}">
                <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="触发" width="90">
              <template #default="{row}">{{ triggerLabel(row.trigger) }}</template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip></el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============ Tab 2：计划任务 ============ -->
        <el-tab-pane label="计划任务" name="cron">
          <div v-if="cron && cron.disabled_by_env" style="margin-bottom:10px">
            <el-alert type="info" :closable="false" show-icon
                      title="当前为测试环境，后台调度线程已关闭；任务仍可手动执行。"></el-alert>
          </div>
          <el-table v-if="cron" :data="cron.jobs" size="small" border>
            <el-table-column prop="name" label="任务" min-width="130"></el-table-column>
            <el-table-column prop="code" label="代码" width="120"></el-table-column>
            <el-table-column label="每日时刻" width="100">
              <template #default="{row}">
                <el-link type="primary" @click="editTime(row)">{{ row.daily_time }}</el-link>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="70">
              <template #default="{row}">
                <el-switch :model-value="row.active" @change="toggleCron(row)"></el-switch>
              </template>
            </el-table-column>
            <el-table-column prop="last_run_date" label="最后执行" width="100"></el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{row}">
                <el-tag v-if="row.last_status" :type="statusTag(row.last_status)" size="small">
                  {{ statusLabel(row.last_status) }}</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="remark" label="说明" min-width="220" show-overflow-tooltip></el-table-column>
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{row}">
                <el-button size="small" :loading="cronRunning === row.code"
                           :disabled="!row.active" @click="runCron(row)">立即执行</el-button>
              </template>
            </el-table-column>
          </el-table>

          <h4 style="margin:16px 0 8px">最近执行留痕</h4>
          <el-table v-if="cron" :data="cron.runs" size="small" border max-height="320">
            <el-table-column label="时间" width="160">
              <template #default="{row}">{{ (row.started_at || '').replace('T', ' ').slice(0, 19) }}</template>
            </el-table-column>
            <el-table-column prop="job_code" label="任务" width="120"></el-table-column>
            <el-table-column label="结果" width="80">
              <template #default="{row}">
                <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="触发" width="90">
              <template #default="{row}">{{ triggerLabel(row.trigger) }}</template>
            </el-table-column>
            <el-table-column label="耗时" width="80">
              <template #default="{row}">
                {{ row.started_at && row.finished_at ? fmtMs((new Date(row.finished_at) - new Date(row.started_at))) : '—' }}
              </template>
            </el-table-column>
            <el-table-column prop="message" label="信息" min-width="240" show-overflow-tooltip></el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============ Tab 3：参数配置 ============ -->
        <el-tab-pane label="参数配置" name="config">
          <div style="display:flex; justify-content:space-between; margin-bottom:10px">
            <el-input v-model="cfgKw" placeholder="按参数键 / 说明搜索" clearable
                      style="width:280px" size="small">
              <template #prefix><el-icon><search></search></el-icon></template>
            </el-input>
            <div style="font-size:12px; color:var(--zc-text-2); align-self:center">
              个税税率表、免征额、科目映射、银行导入映射、官网链接等（ir_config）
            </div>
          </div>
          <el-table :data="filteredCfgs" size="small" border max-height="560">
            <el-table-column prop="key" label="参数键" min-width="200" show-overflow-tooltip></el-table-column>
            <el-table-column label="值" min-width="240" show-overflow-tooltip>
              <template #default="{row}">{{ String(row.value === null || row.value === undefined ? '' : row.value) }}</template>
            </el-table-column>
            <el-table-column prop="remark" label="说明" min-width="160" show-overflow-tooltip></el-table-column>
            <el-table-column label="操作" width="80" fixed="right">
              <template #default="{row}">
                <el-button size="small" @click="editCfg(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ============ Tab 4：审计日志 ============ -->
        <el-tab-pane label="审计日志" name="audit">
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px">
            <el-input v-model="auditFilters.model" placeholder="模型（如 account_move）" clearable
                      style="width:200px" size="small"></el-input>
            <el-select v-model="auditFilters.user_id" placeholder="操作人" clearable
                       style="width:140px" size="small">
              <el-option v-for="u in users" :key="u.id" :value="u.id" :label="u.name"></el-option>
            </el-select>
            <el-date-picker v-model="auditFilters.date_from" type="date" placeholder="开始日期"
                            value-format="YYYY-MM-DD" style="width:140px" size="small"></el-date-picker>
            <span style="align-self:center; color:var(--zc-text-2)">至</span>
            <el-date-picker v-model="auditFilters.date_to" type="date" placeholder="结束日期"
                            value-format="YYYY-MM-DD" style="width:140px" size="small"></el-date-picker>
            <el-button type="primary" size="small" @click="searchAudits">查询</el-button>
            <span style="align-self:center; font-size:12px; color:var(--zc-text-2)"
                  v-if="auditTotal">最近 {{ auditTotal }} 条</span>
          </div>
          <el-table :data="audits" size="small" border max-height="560">
            <el-table-column label="时间" width="160">
              <template #default="{row}">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
            </el-table-column>
            <el-table-column prop="model" label="模型" min-width="140"></el-table-column>
            <el-table-column prop="record_id" label="记录" width="70"></el-table-column>
            <el-table-column label="操作人" width="90">
              <template #default="{row}">{{ userName(row.user_id) }}</template>
            </el-table-column>
            <el-table-column prop="action" label="动作" width="90">
              <template #default="{row}">
                <el-tag size="small" :type="{create:'success',write:'warning',delete:'danger'}[row.action] || 'info'">
                  {{ row.action }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="变更" min-width="220" show-overflow-tooltip>
              <template #default="{row}">{{ shortChanges(row.changes) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>

      <!-- 修改任务时刻弹窗 -->
      <el-dialog v-model="timeDialog" :title="'修改执行时刻：' + timeForm.name" width="360px">
        <el-form label-position="top">
          <el-form-item label="每日执行时刻（HH:MM）">
            <el-input v-model="timeForm.daily_time" placeholder="如 07:30"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="timeDialog = false">取消</el-button>
          <el-button type="primary" @click="saveTime">保存</el-button>
        </template>
      </el-dialog>

      <!-- 编辑参数弹窗 -->
      <el-dialog v-model="cfgDialog" :title="'编辑参数：' + cfgForm.key" width="560px">
        <el-form label-position="top">
          <el-form-item :label="'参数值（' + (cfgForm.remark || 'JSON 或文本') + '）'">
            <el-input v-model="cfgForm.value" type="textarea" :rows="8"
                      placeholder="税率表等 JSON 参数请保持原格式修改"></el-input>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="cfgForm.remark"></el-input>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="cfgDialog = false">取消</el-button>
          <el-button type="primary" @click="saveCfg">保存</el-button>
        </template>
      </el-dialog>
    </div>`,
  });
})();
