// 任务看板（项目书 7.4 / 8.4 KanbanView）——按 state 四列分栏。
// 任务可关联客户（book_id）或为全局任务（留空）；状态流转 todo→doing→done。
window.TaskView = Vue.defineComponent({
  name: 'TaskView',
  data() {
    return {
      columns: [],
      loading: false,
      dialog: false,
      editing: null,
      form: null,
      submitting: false,
    };
  },
  computed: {
    stateMeta() {
      return {
        todo: { label: '待办', color: '#6C757D' },
        doing: { label: '进行中', color: '#17A2B8' },
        done: { label: '已完成', color: '#28A745' },
        cancelled: { label: '已取消', color: '#ADB5BD' },
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
        const r = await ZCAPI.tasks.kanban();
        this.columns = r.columns || [];
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
        this.columns = [];
      }
      this.loading = false;
    },
    async move(task, state) {
      try {
        await ZCAPI.tasks.setState(task.id, state);
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '操作失败');
      }
    },
    async remove(task) {
      try {
        await ElementPlus.ElMessageBox.confirm('确认删除该任务？', '删除任务',
          { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.tasks.remove(task.id);
        ElementPlus.ElMessage.success('已删除');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },
    openNew() {
      this.editing = null;
      this.form = {
        book_id: (window.ZC_STORE && window.ZC_STORE.currentBookId) || null,
        title: '', description: '',
        due_date: '', priority: 'normal',
      };
      this.dialog = true;
    },
    openEdit(task) {
      this.editing = task;
      this.form = {
        book_id: task.book_id,
        title: task.title, description: task.description || '',
        due_date: task.due_date || '', priority: task.priority,
      };
      this.dialog = true;
    },
    async submit() {
      const f = this.form;
      if (!f.title || !f.title.trim()) return ElementPlus.ElMessage.warning('请填写任务标题');
      this.submitting = true;
      try {
        if (this.editing) {
          await ZCAPI.tasks.update(this.editing.id, f);
          ElementPlus.ElMessage.success('已保存');
        } else {
          await ZCAPI.tasks.create(f);
          ElementPlus.ElMessage.success('已创建');
        }
        this.dialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.submitting = false;
    },
    isOverdue(t) {
      if (!t.due_date) return false;
      if (t.state === 'done' || t.state === 'cancelled') return false;
      return t.due_date < new Date().toISOString().slice(0, 10);
    },
  },
  template: `
  <div>
    <div class="view-card">
      <div class="form-head">
        <div style="display:flex; align-items:center; gap:10px">
          <el-icon style="font-size:22px; color:var(--zc-primary)"><odometer></odometer></el-icon>
          <div>
            <div style="font-size:16px; font-weight:600">任务看板</div>
            <div style="font-size:12px; color:var(--zc-text-2)">
              全局任务 + 客户关联任务；逾期/续约提醒任务由系统扫描自动生成
            </div>
          </div>
        </div>
        <div style="flex:1"></div>
        <el-button size="small" type="primary" @click="openNew">
          <el-icon><plus></plus></el-icon> 新建任务
        </el-button>
      </div>

      <div class="kanban" v-loading="loading">
        <div class="kanban-col" v-for="col in columns" :key="col.state">
          <div class="kanban-col-head">
            <span class="kanban-dot" :style="{background: stateMeta[col.state].color}"></span>
            <span>{{ stateMeta[col.state].label }}</span>
            <span class="kanban-count">{{ col.items.length }}</span>
          </div>
          <div class="kanban-body">
            <div class="kanban-card" v-for="t in col.items" :key="t.id" @click="openEdit(t)">
              <div class="kanban-card-title">{{ t.title }}</div>
              <div class="kanban-card-meta">
                <el-tag v-if="t.book_name" size="small" type="info">{{ t.book_name }}</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">全局</el-tag>
                <el-tag size="small" :color="stateMeta[col.state].color" style="color:#fff;border:none;margin-left:4px">
                  {{ stateMeta[col.state].label }}
                </el-tag>
              </div>
              <div class="kanban-card-foot">
                <span v-if="t.due_date" :class="{'task-overdue': isOverdue(t)}">
                  {{ t.due_date }}
                </span>
                <span v-else style="color:var(--zc-text-3)">无截止</span>
                <span class="prio" :class="'prio-' + t.priority">
                  {{ ({low:'低',normal:'普通',high:'高',urgent:'紧急'})[t.priority] }}
                </span>
              </div>
              <div class="kanban-card-actions" @click.stop>
                <template v-if="col.state === 'todo'">
                  <el-button link type="primary" size="small" @click="move(t, 'doing')">开始</el-button>
                  <el-button link type="success" size="small" @click="move(t, 'done')">完成</el-button>
                </template>
                <template v-else-if="col.state === 'doing'">
                  <el-button link type="success" size="small" @click="move(t, 'done')">完成</el-button>
                  <el-button link size="small" @click="move(t, 'todo')">退回</el-button>
                </template>
                <template v-else-if="col.state === 'done'">
                  <el-button link size="small" @click="move(t, 'todo')">重开</el-button>
                </template>
                <el-button link type="danger" size="small" @click="remove(t)">删除</el-button>
              </div>
            </div>
            <div v-if="!col.items.length" class="kanban-empty">暂无任务</div>
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑任务' : '新建任务'" width="520px">
      <el-form v-if="form" label-position="top" size="small">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="任务标题"></el-input>
        </el-form-item>
        <el-form-item label="所属客户（留空 = 全局任务）">
          <el-select v-model="form.book_id" filterable clearable style="width:100%"
                     placeholder="选择客户（可留空）">
            <el-option v-for="b in (window.ZC_STORE ? ZC_STORE.books : [])" :key="b.id"
                       :value="b.id" :label="b.code + ' ' + b.short_name"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="到期日">
              <el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD"
                              style="width:100%"></el-date-picker>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-select v-model="form.priority" style="width:100%">
                <el-option label="低" value="low"></el-option>
                <el-option label="普通" value="normal"></el-option>
                <el-option label="高" value="high"></el-option>
                <el-option label="紧急" value="urgent"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
