// 文档中心（项目书 6.12 / 7.12）：客户资料集中管理
// 拖拽多文件上传 → 按客户/类型/标签/年份筛选 → 图片/PDF 在线预览 → 业务单据挂接反查
window.DocumentsView = Vue.defineComponent({
  name: 'DocumentsView',
  data() {
    return {
      loading: false,
      docs: [],
      total: 0,
      // 筛选
      fBookId: null,
      fDocType: '',
      fTag: '',
      fYear: null,
      fSearch: '',
      // 上传
      dragover: false,
      uploadDialog: false,
      uploadFiles: [],
      uploadForm: null,
      uploading: false,
      // 预览
      previewDialog: false,
      previewDoc: null,
      // 编辑元数据
      editDialog: false,
      editForm: null,
      editSubmitting: false,
      // 标签候选（从现有文档聚合）
      allTags: [],
    };
  },
  computed: {
    books() { return (window.ZC_STORE && window.ZC_STORE.books) || []; },
    currentBookId() { return (window.ZC_STORE && window.ZC_STORE.currentBookId) || null; },
    docTypeMeta() {
      return {
        license: '营业执照', contract: '合同', tax_receipt: '申报回执', bank_slip: '银行回单',
        customs: '报关单', invoice: '发票影像', payroll: '工资表', other: '其他',
      };
    },
    yearOptions() {
      const y = new Date().getFullYear();
      const ys = [];
      for (let i = 0; i <= 6; i++) ys.push(y - i);
      return ys;
    },
  },
  mounted() { this.load(); },
  methods: {
    fmtSize(bytes) {
      const n = Number(bytes) || 0;
      if (n < 1024) return n + ' B';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
      return (n / 1024 / 1024).toFixed(1) + ' MB';
    },
    typeLabel(t) { return this.docTypeMeta[t] || t; },
    typeTag(t) {
      return { license: 'danger', contract: 'primary', tax_receipt: 'warning',
               bank_slip: 'success', customs: 'primary', invoice: 'warning',
               payroll: 'info', other: 'info' }[t] || 'info';
    },
    async load() {
      this.loading = true;
      try {
        const r = await ZCAPI.docs.list({
          book_id: this.fBookId || (this.currentBookId || null),
          doc_type: this.fDocType || null,
          tag: this.fTag || null,
          year: this.fYear || null,
          search: this.fSearch || null,
          limit: 200,
        });
        this.docs = r.records || [];
        this.total = r.total || 0;
        // 聚合标签候选
        const s = new Set();
        for (const d of this.docs) {
          (d.tags || '').split(',').forEach((t) => { if (t.trim()) s.add(t.trim()); });
        }
        this.allTags = Array.from(s);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '加载失败');
      }
      this.loading = false;
    },
    resetFilters() {
      this.fBookId = null; this.fDocType = ''; this.fTag = ''; this.fYear = null; this.fSearch = '';
      this.load();
    },
    sourceLabel(d) {
      if (!d.source_model) return '';
      const names = { invoice_bill: '发票', ft_customs_decl: '报关单',
                      contract_agreement: '合同', res_book: '客户档案' };
      return (names[d.source_model] || d.source_model) + ' #' + d.source_id;
    },
    goSource(d) {
      if (!d.source_model) return;
      const routes = {
        invoice_bill: '#/invoices',
        ft_customs_decl: '#/foreign-trade',
        contract_agreement: '#/contracts',
        res_book: '#/form/res_book/' + d.source_id,
      };
      const r = routes[d.source_model];
      if (r) location.hash = r;
    },

    // ---------- 上传 ----------
    onDrop(ev) {
      this.dragover = false;
      const files = Array.from(ev.dataTransfer.files || []);
      if (files.length) this.openUpload(files);
    },
    onPick(ev) {
      const files = Array.from(ev.target.files || []);
      if (files.length) this.openUpload(files);
      ev.target.value = '';
    },
    openUpload(files) {
      this.uploadFiles = files;
      const y = new Date().getFullYear();
      this.uploadForm = {
        book_id: this.currentBookId || null,
        doc_type: 'other', tags: '', doc_year: y, name: '',
        source_model: '', source_id: null, remark: '',
      };
      this.uploadDialog = true;
    },
    removeUploadFile(i) {
      this.uploadFiles.splice(i, 1);
      if (!this.uploadFiles.length) this.uploadDialog = false;
    },
    async doUpload() {
      const f = this.uploadForm;
      if (!f.book_id) return ElementPlus.ElMessage.warning('请选择文档归属客户');
      this.uploading = true;
      try {
        const r = await ZCAPI.docs.upload(this.uploadFiles, {
          book_id: f.book_id, doc_type: f.doc_type, tags: f.tags,
          doc_year: f.doc_year || null, name: f.name || null,
          source_model: f.source_model || null, source_id: f.source_id || null,
          remark: f.remark || null,
        });
        ElementPlus.ElMessage.success('已上传 ' + r.count + ' 个文件');
        this.uploadDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '上传失败');
      }
      this.uploading = false;
    },

    // ---------- 预览 ----------
    openPreview(d) {
      this.previewDoc = d;
      this.previewDialog = true;
    },
    isImage(d) { return /\.(jpe?g|png|gif|webp|bmp)$/i.test(d.attachment_path || ''); },
    isPdf(d) { return /\.pdf$/i.test(d.attachment_path || ''); },
    download(d) {
      if (d.file_url) window.open(d.file_url + '?download=1', '_blank');
    },

    // ---------- 编辑 / 删除 ----------
    _editingDoc: null,
    openEdit(d) {
      this._editingDoc = d;
      this.editForm = {
        name: d.name, doc_type: d.doc_type, tags: d.tags || '',
        doc_year: d.doc_year || null, remark: d.remark || '',
      };
      this.editDialog = true;
    },
    async submitEdit() {
      const d = this._editingDoc;
      if (!d) return;
      this.editSubmitting = true;
      try {
        await ZCAPI.docs.update(d.id, this.editForm);
        ElementPlus.ElMessage.success('已保存');
        this.editDialog = false;
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '保存失败');
      }
      this.editSubmitting = false;
    },
    async remove(d) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '确认删除文档「' + d.name + '」？（记录归档，文件保留在磁盘）', '删除文档',
          { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' });
      } catch (e) { return; }
      try {
        await ZCAPI.docs.remove(d.id);
        ElementPlus.ElMessage.success('已删除');
        await this.load();
      } catch (e) {
        ElementPlus.ElMessage.error(e.message || '删除失败');
      }
    },
  },
  template: `
  <div>
    <!-- 拖拽上传区 -->
    <div class="view-card" style="margin-bottom:12px">
      <div class="doc-dropzone" :class="{dragover}" @click="$refs.fileInput.click()"
           @dragover.prevent="dragover = true" @dragleave.prevent="dragover = false"
           @drop.prevent="onDrop">
        <div class="dz-icon">📄</div>
        <div style="font-size:14px">把营业执照 / 合同 / 回执 / 回单等文件拖到这里，或点击选择</div>
        <div class="dz-hint">支持多文件 · 单个 ≤ 10MB · 图片 / PDF / Office 文档</div>
      </div>
      <input ref="fileInput" type="file" multiple style="display:none"
             accept=".jpg,.jpeg,.png,.gif,.webp,.bmp,.pdf,.xlsx,.xls,.csv,.docx,.doc,.txt,.zip"
             @change="onPick">
    </div>

    <div class="view-card">
      <div class="form-head" style="margin-bottom:10px; flex-wrap:wrap; gap:8px">
        <el-select v-model="fBookId" placeholder="全部客户" clearable filterable size="small"
                   style="width:170px" @change="load">
          <el-option v-for="b in books" :key="b.id" :value="b.id"
                     :label="b.code + ' ' + b.short_name"></el-option>
        </el-select>
        <el-select v-model="fDocType" placeholder="全部类型" clearable size="small"
                   style="width:120px" @change="load">
          <el-option v-for="(label, v) in docTypeMeta" :key="v" :label="label" :value="v"></el-option>
        </el-select>
        <el-select v-model="fTag" placeholder="标签" clearable size="small" filterable
                   allow-create style="width:120px" @change="load">
          <el-option v-for="t in allTags" :key="t" :label="t" :value="t"></el-option>
        </el-select>
        <el-select v-model="fYear" placeholder="年份" clearable size="small"
                   style="width:90px" @change="load">
          <el-option v-for="y in yearOptions" :key="y" :label="y + ' 年'" :value="y"></el-option>
        </el-select>
        <el-input v-model="fSearch" placeholder="搜名称 / 备注 / 标签" clearable size="small"
                  style="width:180px" @clear="load" @keyup.enter="load"></el-input>
        <el-button size="small" @click="resetFilters">重置</el-button>
        <div style="flex:1"></div>
        <span style="font-size:12px; color:var(--zc-text-2)">共 {{ total }} 份文档</span>
      </div>

      <el-table :data="docs" size="small" border stripe v-loading="loading">
        <el-table-column prop="name" label="文档名称" min-width="180" show-overflow-tooltip></el-table-column>
        <el-table-column prop="book_name" label="客户" width="110"></el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{row}">
            <el-tag size="small" :type="typeTag(row.doc_type)">{{ typeLabel(row.doc_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="tags" label="标签" min-width="120">
          <template #default="{row}">
            <el-tag v-for="t in (row.tags || '').split(',').filter(Boolean)" :key="t"
                    size="small" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="doc_year" label="年份" width="70" align="center"></el-table-column>
        <el-table-column label="关联单据" width="110">
          <template #default="{row}">
            <el-link v-if="row.source_model" type="primary" style="font-size:12px"
                     @click="goSource(row)">{{ sourceLabel(row) }}</el-link>
            <span v-else style="color:var(--zc-text-3)">—</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="80" align="right">
          <template #default="{row}">{{ fmtSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{row}">
            <el-button v-if="row.previewable" link type="primary" size="small"
                       @click="openPreview(row)">预览</el-button>
            <el-button v-if="row.file_url" link size="small"
                       @click="download(row)">下载</el-button>
            <el-button link size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="!docs.length && !loading" class="kanban-empty"
           style="padding:30px; text-align:center; color:var(--zc-text-3)">
        还没有文档，拖个文件上来试试
      </div>
    </div>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadDialog" title="上传文档" width="560px">
      <div style="font-size:13px; margin-bottom:10px">
        已选 <b>{{ uploadFiles.length }}</b> 个文件：
        <div style="margin-top:6px; max-height:120px; overflow:auto; font-size:12px; color:var(--zc-text-2)">
          <div v-for="(f, i) in uploadFiles" :key="i"
               style="display:flex; justify-content:space-between; padding:2px 0">
            <span class="ellipsis">{{ f.name }}</span>
            <span style="flex-shrink:0">{{ fmtSize(f.size) }}</span>
          </div>
        </div>
      </div>
      <el-form v-if="uploadForm" label-position="top" size="small">
        <el-form-item label="归属客户" required>
          <el-select v-model="uploadForm.book_id" filterable style="width:100%">
            <el-option v-for="b in books" :key="b.id" :value="b.id"
                       :label="b.code + ' ' + b.short_name"></el-option>
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="类型">
              <el-select v-model="uploadForm.doc_type" style="width:100%">
                <el-option v-for="(label, v) in docTypeMeta" :key="v" :label="label" :value="v"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="标签">
              <el-input v-model="uploadForm.tags" placeholder="逗号分隔"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="年份">
              <el-select v-model="uploadForm.doc_year" clearable style="width:100%">
                <el-option v-for="y in yearOptions" :key="y" :label="y + ' 年'" :value="y"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="统一命名（可空，多文件自动加序号）">
          <el-input v-model="uploadForm.name" placeholder="留空则用原文件名"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="doUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 在线预览 -->
    <el-dialog v-model="previewDialog" :title="previewDoc ? previewDoc.name : ''"
               width="80%" top="4vh">
      <template v-if="previewDoc">
        <div style="text-align:center" v-if="isImage(previewDoc)">
          <img :src="previewDoc.file_url" :alt="previewDoc.name"
               style="max-width:100%; max-height:70vh">
        </div>
        <iframe v-else-if="isPdf(previewDoc)" :src="previewDoc.file_url"
                style="width:100%; height:70vh; border:1px solid var(--zc-border); border-radius:4px"></iframe>
        <div v-else style="padding:30px; text-align:center; color:var(--zc-text-2)">
          该类型不支持在线预览，
          <el-link type="primary" @click="download(previewDoc)">
            点击下载
          </el-link>
        </div>
        <div style="margin-top:10px; font-size:12px; color:var(--zc-text-2); text-align:center">
          {{ previewDoc.book_name }} · {{ typeLabel(previewDoc.doc_type) }} ·
          {{ fmtSize(previewDoc.file_size) }}
        </div>
      </template>
    </el-dialog>

    <!-- 编辑元数据 -->
    <el-dialog v-model="editDialog" title="编辑文档信息" width="460px">
      <el-form v-if="editForm" label-position="top" size="small">
        <el-form-item label="文档名称">
          <el-input v-model="editForm.name"></el-input>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="类型">
              <el-select v-model="editForm.doc_type" style="width:100%">
                <el-option v-for="(label, v) in docTypeMeta" :key="v" :label="label" :value="v"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="标签">
              <el-input v-model="editForm.tags" placeholder="逗号分隔"></el-input>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="年份">
              <el-select v-model="editForm.doc_year" clearable style="width:100%">
                <el-option v-for="y in yearOptions" :key="y" :label="y + ' 年'" :value="y"></el-option>
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="2"></el-input>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
  `,
});
