# 智财代账工作台（ZhiCai Workbench）

> 一人代理记账公司管 100 家客户账务的 WebUI 工作台。借鉴 Odoo 开源 ERP 的架构思想（模块化、模型驱动 UI、多公司隔离、审计），用轻量技术栈自建（FastAPI + SQLite + Vue3 无构建）。本机部署、零外部服务依赖。

## 快速开始（Windows）

1. 双击 `start.bat` —— 首次运行自动创建虚拟环境、安装依赖、建库
2. 浏览器自动打开 `http://127.0.0.1:8000`
3. 初始账号：**admin / admin123**（登录后请立即在右上角用户菜单修改密码）
4. 系统自带 2 个示例客户账套（宏发五金、远洋外贸），可在「客户管理」里归档后开始录真实客户

关闭 start.bat 窗口即停止服务。**所有数据都在 `data/zhicai.db` 一个文件里**（SQLite），备份 = 复制这个文件。

## 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| 后端 | FastAPI + SQLAlchemy 2.0 | 动态 CRUD API + 元数据 API（模型驱动） |
| 数据库 | SQLite（WAL 模式） | 单文件、零运维、可整体云备份 |
| 前端 | Vue 3 + Element Plus（**全部本地 vendor**） | 无构建、无 Node 依赖、断网秒开 |
| 认证 | 自研会话（itsdangerous 签名 cookie） | 单机应用，仅监听 127.0.0.1 |

## 目录结构（M1 基座）

```
zhicai/
├── start.bat                # 一键启动
├── requirements.txt
├── config.yaml              # 运行配置（首次自动生成）
├── app/
│   ├── main.py              # FastAPI 入口：模块装载→建表→种子
│   ├── core/                # 框架层（对标 Odoo 核心包）
│   │   ├── registry.py      #   模块注册表（addons 装载机制）
│   │   ├── base_model.py    #   BaseModel 约定（审计四字段/软删除/账套隔离）
│   │   ├── domain.py        #   Odoo 风格 domain 过滤语法解析
│   │   ├── security.py      #   密码（pbkdf2）+ 会话 + 角色权限
│   │   ├── sequence.py      #   自动编号（ir.sequence）
│   │   ├── audit.py         #   字段级审计日志（mail.thread）
│   │   └── book_context.py  #   当前账套上下文（多公司切换）
│   ├── api/                 # auth / meta / 动态 CRUD / 业务动作
│   └── modules/             # 业务模块（对标 Odoo addons/）
│       ├── base/            #   用户/角色/参数/审计
│       ├── res_partner/     #   客户账套（res_book）+ 往来单位
│       └── account/         #   会计科目 + 账簿（M1 骨架）
├── static/                  # 前端（无构建）
│   ├── index.html
│   ├── js/app.js            # AppShell + 路由 + 登录 + 仪表盘
│   ├── js/components/       # ListView / FormView 通用渲染器
│   ├── js/modules/          # BookWizard（新建客户向导）等定制页
│   └── vendor/              # CDN 库的本地副本（断网回退）
├── tests/                   # pytest（domain 单测 + API 集成测试）
└── data/                    # 运行时数据（zhicai.db + 附件目录）
```

## 运行测试

```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

## M1 交付范围与验收

- [x] `start.bat` 一键起服务并自动开浏览器
- [x] 新建客户向导产出完整科目表（小企业准则 87 科目含应交税费明细）+ 4 个账簿（记/收/付/转）+ 凭证编号器
- [x] 客户列表筛选（服务中/一般纳税人/小规模/外贸/已终止）/搜索/排序/分页/导出 CSV
- [x] 任意表单保存后活动日志记录字段变更（Chatter：旧值→新值）
- [x] domain 解析器单测全绿（所有运算符/逻辑符/异常分支，20 个用例）
- [x] pytest 覆盖 CRUD API（登录/权限/账套隔离/审计/向导/搜索，30 个用例）

## 假设与决策记录（实施中登记）

| # | 决策 | 原因 |
|---|------|------|
| 1 | M1 用 `create_all` 建表，Alembic 自 M2 引入 | 从零建库阶段无存量表需要迁移；表结构稳定后再上迁移工具降低复杂度 |
| 2 | account 模块在 M1 只建骨架（科目+账簿），凭证等 M2 交付 | 项目书 M1 验收②要求新建客户向导产出科目表+账簿，是 account 的前置依赖；但记账功能按里程碑纪律留给 M2 |
| 3 | 企业会计准则科目模板暂映射小企业模板 | 项目书 6.6 只给了小企业准则明细；企业准则模板在 M2 按需补充（当前无该准则客户） |
| 4 | admin 初始密码 `admin123` 写死在种子 | 单机单用户场景，README 与登录页均提示首次修改 |
| 5 | 示例账套仅在空库时创建 | 避免用户录入真实数据后种子重复造示例 |
| 6 | `res_book` 表允许跨账套查询（白名单） | 客户列表本身即全局视角（对标 Odoo 里的公司列表） |
| 7 | 全局搜索 M1 覆盖客户+科目 | 凭证号/发票号搜索随 M2/M3 交付相应模块后扩展 |
| 8 | Element Plus 中文语言包走本地 vendor | UMD locale 文件小（4.7KB），本地化加载保证断网中文界面 |
| 9 | CRUD 层对 date/datetime/decimal 做统一类型转换 | 前端 JSON 传 ISO 字符串，SQLite 列类型严格，需服务端统一收敛 |

## 数据与备份

- 主库：`data/zhicai.db`（SQLite WAL 模式，断电安全）
- 附件：`data/attachments/`（按 `YYYY/MM/<uuid>.<ext>` 组织，M6 文档中心使用）
- 自动备份（M7 已交付）：在 `config.yaml` 配置 `backup_dir` 后，每日 09:00 自动执行
  `integrity_check → VACUUM INTO` 热备份，滚动保留最近 90 份；未配置目录则跳过并留痕。
  详细操作见下方「M7 验收与运维手册」。

## M1 验收后的紧急修复（2026-09-02）

M1 交付时遇到两个导致"打不开"的真凶，已修：

1. **admin 密码被改坏**（之前测试中改过未还原） → 表现：双击 start.bat 后输入 admin/admin123 显示"账号或密码错误"，卡在登录页。
   - **自修命令**（如果以后再改坏）：
     ```bash
     cd zhicai && .venv\Scripts\python.exe -c "import sys,sqlite3;sys.path.insert(0,'.');from app.core.security import hash_password;c=sqlite3.connect('data/zhicai.db');c.execute(\"UPDATE res_users SET password_hash=? WHERE login='admin'\",(hash_password('admin123'),));c.commit();print('ok')"
     ```
2. **客户详情页（FormView）白屏崩溃** → 表现：菜单点开任意客户后整页空白。
   - **根因**：后端 `init` 类审计日志的 `changes` 是 JSON 对象 `{"message":"..."}`，`write` 类是数组 `[{field,old,new}]`；前端 `FormView.js:176` 用 `(item.changes || []).find()` 假设始终是数组，对象时 `.find` 不存在 → 整页 Vue 抛 TypeError 终止渲染。
   - **修复**：新增 `changesArray()` 工具方法，模板与计算属性统一显式数组判定。`FormView.js` 已加防回归注释。

**其他改进**：
- `start.bat` 端口探测：8000 端口被占时自动换 8001-8010；如服务已在跑则提示并直接打开浏览器（不重复启动）
- 前端去掉 unpkg CDN 依赖（**完全本地化**）：Vue/ElementPlus/icons/locale 全部用 `static/vendor/` 本地副本，断网/CNAME 污染也不会卡白屏
- 新增 `tools/smoke.js`：jsdom 端到端冒烟测试（覆盖登录流程 + 5 个页面真实渲染检查），防白屏回归

## 路线图（见项目书第 10 章）

- **M1（已完成）**：基座与客户管理
- **M2（已完成）**：记账核心（凭证录入/过账/红冲/结转/账簿/报表）
- **M3（已完成）**：发票 + 自动记账 + 银行对账（核心卖点）
- **M4（已完成）**：税务申报台账与日历（防漏报核心）
- **M5（已完成）**：合同收费与任务/仪表盘
- **M6（已完成）**：外贸专区、工资社保、文档中心
- **M6（已完成）**：外贸专区、工资社保、文档中心
- **M7（已完成）**：自动备份加固与收尾 —— 全部里程碑交付完毕

## M2 验收与功能概览

**范围**：account_move 凭证 / account_move_line 分录 / 期末结转 / 期间锁 / 税率 / 三大报表。

**DoD 验证（项目书 7.5）**：
- ① 每张凭证过账校验全通过 → `tests/test_account_m2.py::TestPostValidation` 覆盖 6.5 全部约束分支（不平衡、零额、<2 行、借贷互斥、摘要/科目必填、非末级、辅助核算、重复过账）
- ② 结转后损益科目余额为 0、本年利润正确 → `TestFullAccountingCycle::test_full_cycle` 端到端验证
- ③ 资产负债表「资产=负债+权益」平衡校验内置，不平顶部红条 + 差额 → `balance_sheet()` 返回 `balanced` + `diff` + `warning` 字段，前端 `.report-alert` 渲染
- ④ 利润表净利润 = 本年利润科目发生额 → `_period_amount` 自动排除期末结转凭证（结转会冲平损益）；`TestFullAccountingCycle` 验证一致

**入口（顶栏菜单）**：
- 记账：会计科目 / 账簿设置 / 税率设置
- 记账作业：记账凭证（行内展开 / 批量过账 / 红冲）/ **凭证录入**（定制页：Excel 连续录入、`//` 摘要复制、科目联想、借贷互斥、不平衡禁用"保存并过账"、存为模板）
- 账簿报表：账簿查询（总账/明细账/科目余额表 + CSV 导出）/ 财务报表（资产负债表 + 利润表 + 期末结转 + 期间结账）

**演示数据灌入**（重置 1 号账套为 7 张真实业务凭证并结转）：
```bash
.venv\Scripts\python.exe tools/demo_data.py
```
输出会校验：资产 = 负债 + 权益 ✓，净利润 = 本年利润发生额 ✓。

## M3 验收与功能概览

**范围**：发票登记（进项/销项一张表）+ Excel 导入 + 自动记账规则引擎 + 批量执行工作台 + 银行流水导入与对账。

**DoD 验证（项目书 7.6 / 7.7 / 7.8）**：
- 7.6 导入 500 行 < 5 秒 ✓（`TestInvoiceImport::test_import_500_rows_under_5s` 计时断言）
- 7.6 重复发票拦截 ✓（库内查重 + 批内查重双重）
- 7.6 价税合计 Decimal 精度 ✓（四舍五入、含税反算、3% 小规模不丢分）
- 7.7 **种子规则全链路** ✓（`test_full_chain_8_moves`）：3 销项 + 2 进项 + 3 流水 → 8 张平衡 draft 凭证，科目与金额逐项断言；同批重复执行全部跳过
- 7.7 引擎铁律 ✓（`test_unbalanced_template_rejected`）：模板借贷不平衡 → 整单拒绝 + 写日志
- 7.8 编码容错 ✓（GBK / UTF-8-BOM 自动识别，防表头乱码）
- 7.8 生成凭证后流水状态联动 ✓（`test_generate_move_links_state`）

**新增菜单**：
- 票据与银行：**发票管理**（进项/销项 Tab + Excel 导入向导 + 月末视图）、**银行对账**（左右分栏工作台 + 月度汇总）
- 自动记账：**批量执行**（核心卖点页）、记账规则、执行日志

**内置 6 条种子规则**（新账套自动克隆，可停用/修改，按优先级匹配）：
1. 销项发票 → 借 1122 应收账款{价税合计} / 贷 6001 收入 + 贷 2221.01.01 销项税
2. 进项发票 → 借 {category_account} 费用{不含税} + 借 2221.01.02 进项税 / 贷 2202 应付账款
3. 银行流水「工资」支出 → 借 2211.01 / 贷 1002（优先级 10）
4. 银行流水「税」支出 → 借 2221.02 / 贷 1002（优先级 20）
5. 银行流水收入 → 借 1002 / 贷 1122（优先级 30）
6. 工资批次 → 计提与发放（M6 启用，默认停用）

category→科目映射存 `ir_config`（key `auto_entry.category_account_map`），银行表头别名存
`bank.import.field_map`，都可在「参数配置」里改。

**M3 演示数据**（3 销项 + 2 进项 + 3 流水 → 8 张凭证）：
```bash
.venv\Scripts\python.exe tools/demo_data_m3.py
```
输出会校验：8 张凭证全部借贷平衡，重复执行全部跳过。

**新增依赖**：`openpyxl`（Excel 解析）、`python-multipart`（文件上传）。start.bat 会自动安装。

## M4 验收与功能概览

**范围**：征期规则 + 申报台账批量生成 + 申报日历（月历/列表双视图）+ 计算底稿 + 官网链接中心。

> **重要**：系统**不做自动申报**（政策安全原因），只做登记、计算底稿与官网导航。

**DoD 验证（项目书 7.9）**：
- 征期规则批量生成台账**幂等**且覆盖 **100 账套 < 10 秒** ✓
  （`TestBulkPerformance::test_100_books_under_10s` 计时断言，实测 ~0.1s）
- **逾期自动标红** ✓（`is_overdue` 派生属性：`TestOverdue::test_overdue_flag` 覆盖 6 种组合）
- **每笔计算底稿可追溯取数来源** ✓（`calc_snapshot` 带 `source`，前端数字可穿透到发票/凭证列表）

**新增菜单（税务申报）**：
- **申报日历**：月历/列表双视图切换；状态配色 pending 灰 / preparing 蓝 / submitted 橙 /
  paid 绿 / exempt 白 / **逾期红**；顶部逾期警示条
- 征期规则

**内置 8 条征期规则**：

| 税种 | 小规模 | 一般纳税人 |
|---|---|---|
| 增值税 | 按季（次季首月 15 日） | 按月（次月 15 日） |
| 附加税 | 按季 | 按月 |
| 企业所得税 | 季度预缴（次季首月 15 日）+ 年度汇算（次年 5/31） | 同左 |
| 个人所得税 | 按月（次月 15 日） | 同左 |
| 印花税（买卖合同） | 按季 | 同左 |

传月度属期会自动展开季度项（如 `2026-09` → 同时生成 `2026Q3` 的印花税/所得税预缴），
否则按季税种会被整体漏掉。

**计算口径**（政策参数存 `ir_config`，可在「参数配置」维护）：
- 增值税（一般纳税人）= 销项税额 − 进项税额 − 上期留抵
- 增值税（小规模）= 含税销售额 ÷ (1+3%) × 3%；季度不超 30 万免征
- 附加税 = 实缴增值税 ×（城建 7% + 教育附加 3% + 地方教育附加 2%）
- 印花税 = 计税依据 × 0.3‰（默认取当期购销合计，**可手工调整**）
- **企业所得税 / 个税**：只出取数汇总（营业收入/成本/利润总额），计算以税局端为准

**M4 演示**：
```bash
.venv\Scripts\python.exe tools/demo_data_m4.py
```
批量生成台账 → 逐笔计算 → 打印计算底稿与申报日历汇总。

## M5 验收与功能概览

**范围**：合同与收费计划、收款登记、应收报表、任务看板、首页仪表盘六卡片、逾期/续约扫描。

**DoD 验证（项目书 7.2 / 7.4）**：
- 7.4 收费计划生成**不重复不遗漏**（幂等）✓ — `TestFeeGeneration` 覆盖月 12 期 / 季 4 期 /
  年 1 期，重复生成 `created=0` 且 `skipped=12`
- 7.4 **逾期判定**正确 ✓ — `ContractFeeItem.is_overdue` 派生属性（`TestOverdue::test_overdue_flag`）
- 7.4 逾期标红 + 催收任务、到期前 30 天续约提醒，扫描**幂等** ✓ — 二次扫描 `collection_tasks=0`
- 7.2 仪表盘总览模式**跨账套聚合**正确，数字与明细穿透一致 ✓ — `TestDashboard` + 六卡片端到端验证
- 收款登记：批量勾选多期一键收款、单笔收款/开票、重复收款不重复计入 ✓

**新增菜单**：
- 收费管理：**合同与收费管理**（合同列表 / 收款登记 / 应收报表三 Tab + 合同详情抽屉 + 新建合同弹窗 + 扫描逾期/续约）
- 任务管理：**任务看板**（todo/doing/done/cancelled 四列分栏，状态流转 + 优先级 + 逾期标红）
- 首页工作台六卡片：本月概览 / 申报日历红牌 / 逾期预警 / 待办任务（前 10）/ 收款月历 / 各客户进度（四状态灯）

**关键设计**：
- 合同号 `HT0001` 走 `ir_sequence` 自动编号；收费计划按 `(agreement_id, period)` 幂等展开
- 逾期**双轨口径**：`ContractFeeItem.state` 显式 `overdue`（扫描打标）+ 派生 `is_overdue`（未收且到期日已过），保证仪表盘「逾期未收」口径正确
- 任务 `book_id` 可空 = 全局任务；总览显示全部、指定账套显示「该账套 + 全局」
- 催收任务（`high`）与手工 `urgent` 任务分级：仪表盘「待办任务」按 优先级→到期日 排序，紧急手工任务不被系统催收任务淹没

**M5 演示**（建合同 → 自动生成收费计划 → 批量收款 → 扫描 → 报表 → 仪表盘）：
```bash
.venv\Scripts\python.exe tools/demo_data_m5.py
```

## M6 验收与功能概览

**范围**：外贸专区（报关单 / 收汇结汇 / 出口退税 / 平台链接中心）、工资社保（批次 + 员工行 +
个税累计预扣 + 确认生成凭证）、文档中心（跨账套文档台账 + 拖拽上传 + 在线预览 + 业务单据挂接）。

**DoD 验证（项目书 7.10 / 7.11 / 7.12）**：
- 7.10 **非外贸账套看不到外贸菜单** ✓ — 菜单项标 `foreign_only`，meta_api 查
  `ResBook.is_foreign_trade` 动态过滤（`TestForeignTradeMenu`：全部外贸账套归档后菜单消失）
- 7.10 报关单-收汇关联**未收汇差额**正确 ✓ — 一笔报关多次收汇累计，`unreceived = usd_amount - received`
- 7.11 **个税计算**（月度预扣率表 7 档，5000 起征）✓ — 边界值单测：
  应纳税所得额 3000→90.00 / 3001→90.10 / 12000→990.00 / 12001→990.20 / 25000→3590.00；
  税率表存 `ir_config`（key `payroll.iit_brackets`）可在线更新
- 7.11 批次**确认后凭证自动生成且平衡** ✓ — 计提凭证（借 6602.07/6602.08，贷 2211.01/2211.02）
  + 发放凭证（借 2211.01，贷 1002 实发 + 2211.02 个人社保 + 2221.04 个税），借贷合计断言相等
- 7.12 上传 10MB 内文件正常（超限 / 非法扩展名拒绝）✓；**从发票页上传后文档中心可反查来源单据** ✓
  （发票影像上传自动登记 `doc_document`，`source_model=invoice_bill`）
- 单一窗口 CSV 导入**幂等** ✓ — 表头宽松匹配（报关单号/海关编号等别名），重复导入 `skipped`

**新增菜单**：
- 外贸专区（仅外贸客户存在时显示）：**外贸台账** — 汇总卡片 + 报关单 / 收汇结汇 / 出口退税 /
  平台链接四 Tab；报关单详情含商品行、收汇记录（未收差额）、退税记录
- 工资社保：**工资批次列表** → 详情（员工行编辑 / 个税试算 / 重算 / 确认生成凭证 / 标记发放 / 复制上月）
- 文档中心：拖拽多文件上传区 + 客户 / 类型 / 标签 / 年份筛选 + 图片 / PDF 在线预览 + 关联单据跳转

**关键设计**：
- 外贸数据强校验：报关单 / 收汇 / 退税只能落在外贸账套（`_require_ft_book`）
- 工资批次每账套每期间唯一；`draft` 才可改员工行；确认后锁定并挂两张 draft 凭证（手工过账）
- 文档文件存 `data/attachments/YYYY/MM/`，表存相对路径；预览端点按扩展名给 MIME 并防目录穿越
- 附件扩展名白名单（图片 / PDF / Office / zip），拒绝可执行文件

**M6 演示**（建外贸账套 → 报关单 → 收汇 → 退税流转 → 平台链接 → 工资批次 → 文档上传）：
```bash
.venv\Scripts\python.exe tools/demo_data_m6.py
```

## M7 验收与运维手册

**范围**：SQLite 热备份（integrity_check + VACUUM INTO + 90 份滚动清理 + 备份日志）、
计划任务框架（对标 Odoo ir.cron）、系统设置页（备份/任务/参数/审计四 Tab）、性能压测。

**DoD 验证（项目书 7.13 / 7.14）**：
- 7.13 备份文件可用（**恢复演练**）✓ — `TestBackup::test_backup_ok_file_is_valid_sqlite`
  用 sqlite3 打开备份文件并核对全部注册表存在；未配置目录时记 `skipped` 不报错
- 7.13 滚动清理保留最近 **90 份** ✓ — `test_rolling_cleanup`（keep=2 演示：旧的被删、新的保留）
- 7.13 备份日志可查 ✓ — `backup_log` 表 + 设置页「备份历史」Tab + `GET /api/maintenance/backup/logs`
- 7.14 立即备份按钮 / 恢复引导 / ir_config 可视化编辑 / 审计日志筛选 /
  数据库健康检查（integrity/journal_mode/freelist/wal_size）/ **全量 CSV 导出包**（带 BOM，Excel 直开）✓
- 7.13 计划任务四条 ✓ — backup 09:00 / decl_generate 00:30 / fee_overdue 07:00 / task_reminder 07:30；
  启动时补跑当日错过的任务；执行留痕 `ir_cron_run`；任务异常回滚后单独记 fail

**新增菜单**：系统设置（`#/settings`，四 Tab：备份与恢复 / 计划任务 / 参数配置 / 审计日志）。

### 开启自动备份（推荐指向 OneDrive 目录）

1. 编辑 `zhicai/config.yaml`，把 `backup_dir` 改为 OneDrive 同步目录，例如：
   ```yaml
   backup_dir: C:/Users/weiqi/OneDrive/智财代账备份
   ```
   （目录不存在会自动创建；路径正斜杠或双反斜杠均可）
2. 重启 start.bat（或等计划任务次日 09:00 自动生效；也可在设置页点「立即备份」马上验证一次）
3. 备份文件落在 `{backup_dir}/zhicai_backup/zhicai_YYYYMMDD_HHMM.db`，只保留最近 90 份

### 灾难恢复六步骤（设置页「恢复引导」同款说明）

1. 停止服务：关闭 start.bat 窗口
2. 找到备份文件：`{backup_dir}/zhicai_backup/` 里挑日期最近的 `.db`
3. 把损坏的 `data/zhicai.db`（连同 `zhicai.db-wal`、`zhicai.db-shm` 如有）改名留档
4. 把备份文件复制到 `data/` 并改名为 `zhicai.db`
5. 重新双击 start.bat
6. 登录后到「系统设置 → 数据库健康」确认 integrity 为 ok

> 备份不含 `data/attachments/` 附件目录；重要客户影像请连同该目录一起手动复制。

### 常见问题

- **错过当日时刻的任务还会跑吗？** 会。启动时统一补跑当日尚未执行的任务（含服务关机期间错过的）
- **同一天会重复跑吗？** 不会。每日一次由 `last_run_date` 判定；设置页手动点「执行」默认强制跑（留痕 trigger=manual）
- **测试时不想让后台任务抢跑？** 环境变量 `ZC_DISABLE_SCHEDULER=1`（conftest 已自动设置）
- **想改任务时刻/停用某任务？** 设置页「计划任务」Tab 直接改（HH:MM 格式）或关开关，立即生效

### 性能压测结论（项目书 2.3 / 第 9 章达标）

`tools/perf_seed.py` 模拟 **100 账套 × 10 年**（458,640 张凭证 / 1,834,560 行分录 / 309MB 库）：

| 接口 | 预算 | 实测 P95 | 结果 |
|---|---|---|---|
| 凭证列表 | <300ms | ~13ms | ✓ |
| 总账查询 | <300ms | ~16ms | ✓ |
| 科目余额表 | <300ms | ~20ms | ✓（优化前 381ms，N+1 消除后 19 倍提速） |
| 资产负债表 | <1000ms | ~30ms | ✓ |
| 利润表 | <1000ms | ~26ms | ✓ |
| 仪表盘 | <1000ms | ~34ms | ✓ |
| 客户列表 | <300ms | ~9ms | ✓ |

索引核查：account_move / account_move_line / invoice_bill / decl_item 四张关键表
book_id / period / move_date / account_id 索引全部就位。
复跑压测：`.venv\Scripts\python.exe tools/perf_seed.py --fresh`（会重建 data/perf.db，跑完可删）。
