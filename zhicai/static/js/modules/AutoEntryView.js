// 自动记账批量执行工作台（项目书 7.7）——本项目核心卖点页面。
// 流程：选期间 → 列出未生成凭证的发票/流水 → 逐条显示命中规则与预览分录
//      → 勾选 → 批量生成 draft 凭证 + 执行日志。匹配不到规则的留在待人工清单。
window.AutoEntryView = Vue.defineComponent({
  name: 'AutoEntryView',
  data() {
    const d = new Date();
    return {
      period: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      items: [],
      loading: false,
      showUnmatched: true,
      selected: [],
      executing: false,
      result: null,
      logs: [],
      activeTab: 'pending',
    };
  },
  computed: {
    monthOptions() {
      const y = new Date().getFullYear();
      return Array.from({ length: 12 }, (_, i) => ({
        value: `${y}-${String(i + 1).padStart(2, '0')}`, label: `${i + 1} 月`,
      }));
    },
    matchedCount() { return this.items.filter((i) => i.matched).length; },
    unmatchedCount() { return this.items.filter((i) => !i.matched).length; },
    visibleItems() {
      return this.showUnmatched ? this.items : this.items.filter((i) => i.matched);
    },
  },
  mounted() { this.load(); this.loadLogs(); },
  methods: {
    fmt(v) {
      const n = parseFloat(v) || 0;
      return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    },
    typeLabel(m) {
      return { invoice_bill: '发票', bank_statement_line: '银行流水' }[m] || m;
    },
    srcName(it) {
      const s = it.source;
      if (it.source_model === 'invoice_bill') {
        return `${s.invoice_no}（${s.partner_name || '—'}）`;
      }
      return s.summary || s.counterpart_name || `流水#${it.source_id}`;
    },
    srcAmount(it) {
      const s = it.source;
      if (it.source_model === 'invoice_bill') return this.fmt(s.total_amount);
      const amt = parseFloat(s.debit) > 0 ? s.debit : s.credit;
      return this.fmt(amt);
    },

    async load() {
      this.loading = true;
      this.result = null;
      try {
        const r = await ZCAPI.ae.pending(this.period);
        this.items = r.items || [];
        // 默认勾选所有已匹配规则的
        this.$nextTick(() => {
          const table = this.$refs.table;
          if (!table) return;
          table.clearSelection();
          this.items.forEach((it) => {
            if (it.matched) table.toggleRowSelection(it, true);
          });
        });
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
        this.items = [];
      }
      this.loading = false;
    },
    async loadLogs() {
      try {
        const r = await ZCAPI.ae.logs();
        this.logs = r.logs || [];
      } catch (e) { this.logs = []; }
    },
    onSelectionChange(rows) { this.selected = rows; },

    async execute() {
      if (!this.selected.length) {
        return ElementPlus.ElMessage.warning('请先勾选要执行的单据');
      }
      this.executing = true;
      try {
        const items = this.selected.map((i) => ({
          source_model: i.source_model, source_id: i.source_id, rule_id: i.rule_id,
        }));
        this.result = await ZCAPI.ae.execute(items);
        const r = this.result;
        if (r.ok > 0) {
          ElementPlus.ElMessage.success(
            `已生成 ${r.ok} 张凭证${r.skipped ? `，跳过 ${r.skipped} 条` : ''}` +
            `${r.failed ? `，失败 ${r.failed} 条` : ''}`);
        } else if (r.failed > 0) {
          ElementPlus.ElMessage.error(`${r.failed} 条执行失败，详见下方结果`);
        } else {
          ElementPlus.ElMessage.info('没有可执行的单据（可能都已生成过凭证）');
        }
        this.load();
        this.loadLogs();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '执行失败');
      }
      this.executing = false;
    },

    openMove(id) { location.hash = '#/move/' + id; },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><magic-stick></magic-stick></el-icon>
          <div>
            <div style="font-size:16px; font-weight:600">自动记账 · 批量执行</div>
            <div style="font-size:12px; color:var(--zc-text-2)">
              按规则把发票与银行流水批量转成凭证（生成的是草稿，过账前可修改）
            </div>
          </div>
        </div>
        <div style="flex:1"></div>
        <el-button size="small" type="primary" :loading="executing"
                   :disabled="!selected.length" @click="execute">
          <el-icon><caret-right></caret-right></el-icon>
          执行生成（{{ selected.length }}）
        </el-button>
      </div>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="待处理单据" name="pending">
          <el-form :inline="true" size="small" style="margin: 12px 0">
            <el-form-item label="期间">
              <el-select v-model="period" style="width:110px">
                <el-option v-for="m in monthOptions" :key="m.value" :label="m.label" :value="m.value"></el-option>
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="load">刷新清单</el-button>
            </el-form-item>
            <el-form-item>
              <el-checkbox v-model="showUnmatched">显示未匹配的待人工项</el-checkbox>
            </el-form-item>
          </el-form>

          <div class="ledger-total-line" style="margin-bottom:12px">
            共 <b>{{ items.length }}</b> 条待处理，
            命中规则 <b style="color:var(--zc-success)">{{ matchedCount }}</b> 条，
            待人工 <b style="color:var(--zc-warning)">{{ unmatchedCount }}</b> 条
            <span style="font-size:12px; color:var(--zc-text-2); margin-left:8px">
              （已生成凭证的单据不会出现在本清单，重复执行不会重复生成）
            </span>
          </div>

          <el-table ref="table" :data="visibleItems" border size="small" v-loading="loading"
                    height="430" @selection-change="onSelectionChange"
                    :row-class-name="({row}) => row.matched ? '' : 'ae-unmatched-row'">
            <el-table-column type="selection" width="46"
                             :selectable="(row) => row.matched"></el-table-column>
            <el-table-column label="类型" width="90">
              <template #default="{ row }">{{ typeLabel(row.source_model) }}</template>
            </el-table-column>
            <el-table-column label="单据" min-width="170">
              <template #default="{ row }">
                <div>{{ srcName(row) }}</div>
                <div style="font-size:12px; color:var(--zc-text-2)">
                  {{ row.source.invoice_date || row.source.trade_date }}
                  · 金额 {{ srcAmount(row) }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="命中规则" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.matched" size="small" type="success">{{ row.rule_name }}</el-tag>
                <el-tag v-else size="small" type="warning">{{ row.error || '未匹配' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="预览分录" min-width="330">
              <template #default="{ row }">
                <div v-if="row.lines.length">
                  <div v-for="(l, i) in row.lines" :key="i"
                       style="font-size:12px; line-height:1.8; white-space:nowrap">
                    <span :style="{color: l.side==='debit' ? 'var(--zc-text)' : 'var(--zc-primary)',
                                   display:'inline-block', width:'28px'}">
                      {{ l.side === 'debit' ? '借' : '贷' }}
                    </span>
                    <span style="color:var(--zc-text-2)">{{ l.account_code }} {{ l.account_name }}</span>
                    <span style="float:right; margin-left:12px">
                      {{ fmt(l.side === 'debit' ? l.debit : l.credit) }}
                    </span>
                    <span style="color:var(--zc-text-3); margin-left:8px">{{ l.summary }}</span>
                  </div>
                  <div style="font-size:12px; margin-top:4px; color:var(--zc-text-2)">
                    合计 借 {{ fmt(row.total_debit) }} / 贷 {{ fmt(row.total_credit) }}
                    <el-tag size="small" type="success" style="margin-left:6px">平衡</el-tag>
                  </div>
                </div>
                <span v-else style="color:var(--zc-text-3); font-size:12px">—</span>
              </template>
            </el-table-column>
          </el-table>

          <!-- 执行结果 -->
          <div v-if="result" class="ledger-total-line" style="margin-top:12px">
            执行结果：
            <b style="color:var(--zc-success)">成功 {{ result.ok }}</b> ／
            <b style="color:var(--zc-danger)">失败 {{ result.failed }}</b> ／
            <b style="color:var(--zc-warning)">跳过 {{ result.skipped }}</b>
            <div v-if="result.details.failed.length" style="margin-top:8px">
              <div v-for="(f, i) in result.details.failed" :key="i"
                   style="font-size:12px; color:var(--zc-danger)">
                ✗ {{ typeLabel(f.source_model) }}#{{ f.source_id }}：{{ f.message }}
              </div>
            </div>
            <div v-if="result.details.ok.length" style="margin-top:8px">
              <div v-for="o in result.details.ok" :key="o.move_id"
                   style="font-size:12px; color:var(--zc-success)">
                ✓ {{ typeLabel(o.source_model) }}#{{ o.source_id }} →
                <el-link type="primary" @click="openMove(o.move_id)">凭证 #{{ o.move_id }}</el-link>
                （{{ o.rule_name }}）
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="执行日志" name="logs">
          <el-table :data="logs" border size="small" height="460">
            <el-table-column prop="created_at" label="时间" width="160"></el-table-column>
            <el-table-column label="源单据" width="180">
              <template #default="{ row }">{{ typeLabel(row.source_model) }}#{{ row.source_id }}</template>
            </el-table-column>
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="{ok:'success', failed:'danger', skipped:'warning'}[row.result]">
                  {{ {ok:'成功', failed:'失败', skipped:'跳过'}[row.result] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="凭证" width="90">
              <template #default="{ row }">
                <el-link v-if="row.move_id" type="primary" @click="openMove(row.move_id)">
                  #{{ row.move_id }}
                </el-link>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="220"></el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
  `,
});
