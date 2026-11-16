# Xero AU 业务解析及 FINOVA vs LedgerFlow AU 源码级三方对比评审报告

> **评审日期：** 2026-11-16（基于 FINOVA `minimal-ledger` 最新源码重校）  
> **对照三方：**  
> 1. **真实 Xero（AU 版）基准**：基于 [Xero-Research](file:///D:/ai-work/au-faiw/xero调研/Xero-Research/README.md) 中对 `go.xero.com`（空账套 `!W5gW!`、AU Demo `!VD61z`）及官方文档实证，结合 FINOVA 对 Xero `Kungeek` 的只读截图对照。  
> 2. **对方复刻成果（FINOVA）**：[minimal-ledger](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger) 最新源码库（`app/*.py`、`static/app.js`、`tests/*.py`、`docs/*.md` 与 `docs/FINOVA*.pdf`，迭代至 `2026-11-15 08:40`）。  
>    > **重要版本澄清：** 外层 [xero调研-2](file:///D:/ai-work/au-faiw/xero调研-2) 的 3 个 PDF 为 `2026-11-14 23:24` 旧版本；`minimal-ledger` 内部版本新增了 `app/reconcile.py`（完整银行对账 Match/Create/Transfer/Rules）、将默认科目扩展到 36 个、并补跑了六行业测试与 42 项对账隔离测试。**本报告全部以最新源码为准。**  
> 3. **己方复刻成果（LedgerFlow AU）**：[Accounting-SaaS-Blueprint](file:///D:/ai-work/au-faiw/xero调研/Accounting-SaaS-Blueprint/README.md)、[app/](file:///D:/ai-work/au-faiw/xero调研/app) 最新源码（含审计后补修及 `14 passed in 6.92s` Pytest 回归验证）与 [MVP-Acceptance-Audit](file:///D:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/00_MVP独立验收总报告.md)。  
>
> **证据口径图例：**  
> - **`[双方源码实证]`**：本轮直接审阅 FINOVA `minimal-ledger` 与 LedgerFlow AU `app/` 源码确认。  
> - **`[实测运行]`**：在本轮或项目内自动化测试实际运行通过。  
> - **`[Xero基准]`**：来自 Xero Web 实操或官方文档规则。

---

## 第一部分：评审总览与核心定位对比

### 1.1 一句话定性

| 评估维度 | 真实 Xero（AU 版） | FINOVA（对方最新源码 `minimal-ledger`） | LedgerFlow AU（己方 `app/`） |
|---|---|---|---|
| **产品路线** | 商业级全功能澳洲云端会计与生态平台 | **业务闭环 & UI 外观快速复刻**：把开票、银行对账、简化薪酬、Full BAS/TPAR 全部做出可演示页面 | **会计内核 & 专业控制优先**：物理不可变总账 + 深度银行对账 + 全状态商业单据 + AU Simpler BAS |
| **工程架构** | 多租户分布式云架构 | **单进程全量快照（Snapshot）**：FastAPI + Pydantic + SQLite（22 表，无触发器）+ 原生 JS（2,299 行） | **前后端分离 RESTful**：Flask 3 + SQLite WAL（33 表 + **6 不可变触发器**）+ React 18 / TS / Vite |
| **核心优势** | 全生态合规闭环与极高交互成熟度 | **已做 Payroll AU 最小集 + Full BAS（含 G2/G3/G5/G6/W1/W2）+ TPAR + 自定义税率 + 新版对账 UI + 图文手册** | **物理防删改总账 + Credit Note 全闭环 + 完整对账边界（Split/微调/Remove&Redo）+ 双层锁账/RBAC/Tracking/Find&Recode + 精确 Cash BAS** |
| **源码审计发现的核心缺陷** | 闭源商业软件 | 1. **`void_journal()` 物理 `DELETE` 已过账分录**（破坏审计追踪）；<br>2. **Cash BAS 下 `1A/1B` 仍按发票日算（实为 Accrual），且部分收款重复计入整单净额**；<br>3. **财务报表无日期区间筛选**；无 Credit Note、无锁账/RBAC、无行级数量单价 | 1. **尚无真实 JWT 登录态**（`get_actor` 取首行用户，`/auth/switch-role` 可切换角色）；<br>2. **缺 Payroll/TPAR/Full BAS 的 `G2/G3/G5/G6/W1/W2`**；<br>3. 前端缺 URL 路由、部分报表无趋势图、500px 窄屏有横向溢出 |

### 1.2 全站 11 大业务模块全景对照表

| 模块域 | 真实 Xero AU | FINOVA（最新源码实证） | LedgerFlow AU（最新源码实证） |
|---|---|---|---|
| **1. 全局导航与首页** | 64px 蓝顶栏、`+` 快捷键、Twin Balances、AR/AP、现金流图、Watchlist | 64px 蓝顶栏（含 Payroll/Tax 一级菜单）、首页 4 卡 + Tasks 摘要；**无 Watchlist、无现金流图、无快捷键** | 64px 蓝顶栏（`Alt+I/B/C/J/Q/O` 快捷键、`READONLY` 防护）、首页 Twin Balances（含 Overdraft 标）、AR/AP（已扣减 CN）、Watchlist；**缺现金流柱图与 URL 路由** |
| **2. Sales（销售与应收）** | Quotes / Invoices / Repeating / Credit Notes / Payments | Quotes→Invoices→部分/全额收款；**无数量×单价、无 Credit Note、无 Void/Draft 删除/改单** | Quotes（编辑/状态/删除/转单）→Invoices（数量×单价、Draft 删除、Authorised 改单、Void）→**Credit Notes（核销/解绑/现金退款）**→Payments（含撤回） |
| **3. Purchases（采购与应付）** | PO / Bills / Repeating / Supplier CN / ABA Batch Pay | PO→Bills→部分/全额付款；**无 Supplier CN、无 Void/删除/改单、无 ABA** | PO→Bills→**Supplier CN**→Payments；全生命周期支持；双方均未做 **Repeating 单据**与 **ABA 批量付款** |
| **4. Contacts & Products** | 双身份联系人、默认科目税码、Groups/合并；目录+Tracked 库存 | `contact` 含 **`contractor` + `abn`**（联动 TPAR），重名覆盖更新；基础 `item`（无编辑/删除） | `contacts` 含默认销售/采购科目与税率、ABN；`products` 支持新建/编辑/归档；**无 `contractor` 标记**；双方均不做 Tracked 库存 |
| **5. Banking（银行与对账）** | Twin Balances、CSV 去重、Match(Split/微调)/Create/Transfer/Discuss、Unreconcile/Remove&Redo、Cash Coding、Bank Rules | **已补强**：Twin Balances、Match（多单合并整付/匹配 Pay/Journal）、`Find & Match`、Create（单行）、Transfer（已做防重）、`OK X unique`、单行 Cash Coding、简单 Bank Rules；**不支持部分核销与尾差微调、Unreconcile 直接物理删分录、Discuss 不落库** | **深度还原**：CSV 同日同额 `occurrence_idx` 去重、Match（**含部分核销与 Minor Adjustment 尾差**）、Create（多行拆分）、Transfer（双向建议+防重）、`Unreconcile` & `Remove & Redo`（不可变冲销含尾差）、**批量原子 Cash Coding**、**ALL/ANY + 比例拆分 Bank Rules** |
| **6. Accounting（总账与控制）** | 54 科目控制锁、不可变总账、MJ（含税/Auto-Reverse）、Tracking、Conversion、Find & Recode、Assurance | **36 AU 科目**（可新增不重码科目）；基础平衡 MJ（无 Draft/Void/含税/Auto-Reverse、**未屏蔽 610/800/090/820**）；**无 Tracking/Conversion/Find&Recode/Assurance/不可变触发器** | **54 AU 科目（47 可选过滤）**、**6 个 SQLite 物理不可变触发器**、MJ（Draft/Posted/Void/Edit/含税反向/Auto-Reverse）、**2 组 Tracking**、**Conversion Balances**、**Find & Recode**、**Assurance & Audit Log** |
| **7. Reporting（财务报表）** | 区间/截止日 P&L(Accrual/Cash)、BS(跨年结转/透支重分类)、TB、Aged AR/AP、Acct Tx、Cash Flow | P&L、BS、TB、Aged AR/AP、Acct Tx；**全部按全历史汇总，无日期筛选、无 Cash P&L、无跨年虚拟结转、无透支重分类、无 Cash Flow 预测** | 完整日期/截止日筛选、**Accrual/Cash P&L + Tracking 过滤**、**BS 跨财年虚拟结转 + 负银行重分类 Overdraft**、TB、Journal Report、Acct Tx（Watchlist 穿透）、Aged AR/AP、**Short-term Cash Flow**、**全表 CSV 导出** |
| **8. AU Tax（BAS & TPAR）** | 11 税码、Simpler/Full BAS、Cash 按比例分摊、Worksheet/Audit、水位线 Unfiled、TPAR、ATO SBR | **6 税码 + 支持新增自定义税率**；**Full BAS（G1/G2/G3/G5/G6/G10/G11/1A/1B/W1/W2/9）+ Worksheet + Audit + TPAR**；但 **Cash BAS 下 `1A/1B` 错按 Accrual 算且部分收款整单重复计入** | **11 税码**（暂不能新增）；**Simpler BAS + `G10/G11` + 按税率汇总 + GST Audit Report + CSV**；**G1 含/不含税切换 + Whole Dollar 整元 + Cash 按付款比例分摊 + Finalise 水位线追补 Unfiled**；缺 `G2/G3/G5/G6`、`W1/W2` 与 `TPAR` |
| **9. Payroll AU & STP** | 员工、ATO 税表、假期、工时、Pay Run、`804` 过渡、SuperStream、STP2 | **已做简化闭环**：员工（整数小时）、休假、工时、Pay Run 过账（15% 固定 PAYG、12% Super、**直扣 `090` 跳过 `804`**）、STP 页面（不发送） | **仅 Stage 2 占位**（展示规划并读取 `477/478/804/825/826` 活科目余额）；预留 `PAYROLL` 枚举 |
| **10. 重资产与外围域** | Fixed Assets 折旧、Projects、Expense Claims、App Store | **无独立菜单**（仅采购可选 `720` 计入 `G10`） | **Stage 2 占位页 + 活科目余额联动 + `connected_apps` 骨架表** |
| **11. Settings / RBAC / 锁账** | 组织/财税设置、多角色 RBAC、Soft/Hard Lock Dates | 组织/前缀/默认科目税码/GST 期间与口径/发薪费率设置；**无用户表、无 RBAC、无锁账** | 组织/财税/双层锁账设置；**3 级业务角色（Adviser/Standard/ReadOnly）+ Soft/Hard Lock Dates**（仍缺真实登录认证） |

---

## 第二部分：分模块业务解析与三方源码级对比

---

### 模块 1：全局导航与首页工作台（Home & Global Shell）

#### 1.1 Xero 真实业务规则
`[Xero基准]` Xero 顶栏采用 64px 蓝色导航条（组织下拉 + 一级业务域 + 右侧 `+` 快捷新建 `Alt+I/B/C/J/S/R/T/Q/O`），首页驾驶舱核心解决：**一眼掌握银行真假余额差异（Twin Balances）、应收应付及逾期风险、月度现金流柱状趋势、重点科目 YTD 监控（Watchlist）与待办引导**。

#### 1.2 三方能力与源码对比
| 对比项 | 真实 Xero AU | FINOVA（`static/app.js`）`[双方源码实证]` | LedgerFlow AU（`TopNav.tsx` / `DashboardView.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **顶栏导航结构** | 64px 蓝顶栏 | 64px `#1f68dd` 蓝顶栏（Home/Sales/Purchases/Reporting/Payroll/Accounting/Tax/Contacts + 右侧 `+`），组织菜单固定排序（Kungeek 置顶） | 64px 蓝顶栏（Dashboard/Business/Accounting/Reports/Payroll & More/Settings + `+` 快捷新建 + 角色切换徽标） |
| **快捷键新建** | 支持 `Alt+...` 快捷键 | **未实现** | **已实现** `Alt+I/B/C/J/Q/O`，且 `READONLY` 角色下物理拦截 |
| **银行卡展示** | 每家银行独立展示 Twin Balances 与待对账数 | 首页只展示**所有银行净值汇总** `Balance in books`；需点进 Accounting→Bank accounts 才见分卡 Twin Balances | 首页直接列出每家银行 **Statement vs Balance in LedgerFlow**、`Overdraft` 徽标、待对账按钮、Cash Coding 与 Import CSV 快捷入口 |
| **AR / AP 概览** | 含逾期笔数与金额 | 展示 `Invoices owed to you` / `Bills to pay` 及逾期（因无 Credit Note，无需净额扣减） | 展示应收/应付及逾期，**AR 卡片已精确扣减未分配 Credit Note** |
| **Watchlist / 现金流 / 路由** | 有 Watchlist、现金流柱图、完整 URL 深链接 | 首页有 `Net profit` 卡与 BAS 摘要 `Tasks`；**无 Watchlist、无现金流图**；支持 `#` 或状态变量 `view` 切页，刷新回默认 | 有 **Account Watchlist**（可穿透至科目流水）与 Recent Payments；**无现金流柱图**；[App.tsx](file:///D:/ai-work/au-faiw/xero调研/app/frontend/src/App.tsx) 纯内存 `useState` 路由，刷新回首页 |

#### 1.3 相同点与核心差异
* **相同点**：均复刻了 64px 蓝顶栏与组织切换器、右上角 `+` 全局新建弹窗，以及首页 AR/AP/银行余额卡片网格。
* **核心差异**：FINOVA 首页偏向“总账净利润+BAS 进度摘要”；LedgerFlow AU 首页更贴近 Xero 实操工作台（Twin Balances 差额直达对账、Watchlist 穿透、快捷键与只读角色防护）。

---

### 模块 2：销售与应收账款（Sales & Accounts Receivable）

#### 2.1 Xero 真实业务规则
`[Xero基准]` 完整链路为：`Quotes`（不过账，成交转发票）→ `Invoices`（`DRAFT` 不过账；`AUTHORISED` 借 `610 AR` / 贷 `200 收入` & `820 GST`；行项目支持 `数量 × 单价` 与 `Inclusive/Exclusive/No Tax`）→ `Payments`（只冲 `Bank <-> 610 AR`，支持部分收款与撤回）→ `Credit Notes`（退货折让冲减收入与 GST，支持核销发票、解除核销与现金退款）→ `Void` / `Edit` / `Delete Draft`。

#### 2.2 三方能力与源码对比
| 对比项 | 真实 Xero AU | FINOVA（`posting.py` / `db.py`）`[双方源码实证]` | LedgerFlow AU（`documents.py` / `CommercialViews.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **Quotes（报价）** | 状态完整（Draft/Sent/Declined/Accepted/Invoiced）、编辑、删除、转发票 | 存在 `invoice` 表（`doc_type='QUOTE'`），不过账，`Convert` 成 `ACCREC` 后置 `INVOICED`；**无编辑/状态流转/删除** | 独立 `quotes` 表，支持新建、**编辑、状态切换（SENT/ACCEPTED）、删除、幂等转发票**（删转换后的草稿发票会安全重置报价状态） |
| **行项目数据结构** | 支持 `Quantity × UnitPrice` + 折扣 + Tracking | **`invoice_line` 无 `quantity` 和 `unit_price` 列**，仅单总额字段 `gross_cents/amount_cents` | **完整支持 `quantity`、`unit_amount`（4位小数）、行级 `Decimal ROUND_HALF_UP` 算税、Tracking 1/2** |
| **单据编号递增** | 按组织连续递增 | `seq` 按组织递增，但号码 `f"{prefix}-{count+1:04d}"` 按**现有行数**算（若将来删单会重号） | 独立 `org_counters` / 序列控制，无重号隐患 |
| **Draft 删除 / 已审核改单 / Void** | 均支持 | **均不支持**（仅支持 `DRAFT -> AUTHORISED` 审批；一旦过账不能 Void 也不能改单） | **全支持**：Draft 物理删除、未付款 Authorised 改单（冲销原凭证+重过账）、Void（独立冲销凭证） |
| **Payments（收款）** | 部分收款、防超付、撤回付款 | 支持部分/全额收款（`PARTIAL`/`PAID`）、防超付；仅在银行 `unreconcile` 时内部 `DELETE payment`（发票详情页不能独立撤回付款） | 支持部分/全额收款、防超付，发票详情页支持 **`Remove & Reverse` 撤回付款**（生成冲销凭证并重开欠款） |
| **Sales Credit Notes** | 新建、Allocate、Unallocate、Cash Refund | **完全未实现** | **全链路已实现**（新建/审批、Allocate 核销、**Unallocate 解绑**、**Record Cash Refund 现金退款**及删除退款） |

#### 2.3 相同点与核心差异
* **相同点**：均实现了 Quote 不过账转发票才过账、Draft 不过账、Authorised 借 `610` 贷收入与 `820`、收款不再二次记 GST、以及结清后拒绝超收。
* **核心差异**：FINOVA 缺失 **数量×单价模型、Credit Note 全链路、Draft 删除、Authorised 改单与 Void**；LedgerFlow AU 已补齐商业单据完整生命周期（仅缺 Repeating Invoices 与邮件/PDF 生成）。

---

### 模块 3：采购与应付账款（Purchases & Accounts Payable）

#### 3.1 Xero 真实业务规则
`[Xero基准]` `Purchase Orders`（不过账，`Copy to Bill`）→ `Bills`（借费用或固定资产 / 借 `820 GST` / 贷 `800 AP`）→ `Supplier Credit Notes` → `Payments` / `ABA Batch Payments`。

#### 3.2 三方能力与源码对比
* **相同点**：双方均已打通 PO 不过账转 Bill 过账、费用 vs 固定资产科目分流至 BAS `G11/G10`、部分与全额付款、以及结清后拒绝重复付款。
* **核心差异**：
  - FINOVA 的 `ACCPAY` 同样缺失 **数量×单价、Supplier Credit Notes、Void、Draft 删除、已审核改单与独立撤回付款**；
  - LedgerFlow AU 完整实现了采购端全生命周期（含 `ACCPAYCREDIT` 核销与现金退款）；
  - **双方共同缺口**：均未实现 **Repeating Bills** 与澳洲企业常用的 **`.aba` 批量付款文件导出**。

---

### 模块 4：往来联系人与商品/库存（Contacts & Products / Inventory）

#### 4.1 三方能力与源码对比
| 对比项 | 真实 Xero AU | FINOVA（`db.py` / `tax.py` / `main.py`）`[双方源码实证]` | LedgerFlow AU（`core_routes.py` / `ContactsAndSettingsView.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **联系人模型** | 统一 `contacts`、角色自动归类、默认科目税率、Groups、合并、往来明细页 | 统一 `contact` 表，按单据动态推导 `customer`/`supplier`；**含 `contractor` 布尔标记与 `abn`**（同名 POST 覆盖更新标记）；**无默认科目/税率、无编辑/归档、无明细页** | 统一 `contacts` 表，支持 `isCustomer`/`isSupplier`、**ABN**、**默认销售/采购科目与税率预设（开单自动带出）**、弹窗编辑；**缺 `contractor` 标记与往来对账单页** |
| **Products & Services** | 无追踪目录（成本/售价/科目/税率）+ Tracked Inventory（`630/310` 移动加权平均） | `item` 表含 `code/name/sale_price_cents/account_code/tax_code`（无成本价，仅可新增、不能编辑或删除） | `products` 表含成本价/售价/默认科目税码，**支持新建、编辑（PATCH）与归档（DELETE）** |
| **Tracked Inventory** | 完整进销存数量与移动加权 COGS | **未实现** | **未实现**（仅保留表字段骨架，延后至 Stage 2+） |

---

### 模块 5：银行账户、对账与现金编码（Banking, Reconciliation & Cash Coding）

> **源码核实后重大更新：** FINOVA 在 `2026-11-15` 最新代码 `app/reconcile.py`（678 行）及 `static/app.js` 中，**已经补建了非常像 Xero 的四栏对账 UI 与匹配/规则逻辑**。下面基于双方源码做逐行级精细对比。

#### 5.1 Xero 真实业务规则
`[Xero基准]` Twin Balances → CSV 导入去重 → 四栏对账（**Match** 支持多选、部分收款 Split、Minor Adjustment 尾差；**Create** 支持多行拆分与银行规则固定+比例拆行；**Transfer** 双边互转防重；**Discuss** 持久化沟通记录；**Find & Match** 搜索匹配）→ **Cash Coding**（类 Excel 批选批量入账）→ **Unreconcile（仅解绑） vs Remove & Redo（冲销交易并退回流水）**。

#### 5.2 三方能力与源码深度对比
| 能力子项 | 真实 Xero AU | FINOVA（`reconcile.py` / `static/app.js`）`[双方源码实证]` | LedgerFlow AU（`banking.py` / `BankingReconcileView.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **Twin Balances** | Statement vs Book 双余额 | **已实现**（银行卡片及对账页顶部展示 `Statement Balance` vs `Balance in FINOVA`） | **已实现**（首页及银行页展示 `Statement Balance` vs `Balance in LedgerFlow` + 透支标） |
| **CSV 导入去重** | 自动防重 | **无去重防护**（`import_statement` 直接 `INSERT`，重复提交会重复建行） | **已实现 `occurrence_idx` 同日同额多笔流水区分与批导入防重** |
| **对账四栏 UI** | Match / Create / Transfer / Discuss + Find & Match | **高保真 UI**（截图见 [finova-recon-match.png](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/docs/images/finova-recon-match.png)）：含 Match / Create / Transfer / Discuss / Find & Match，绿卡提示唯一匹配 | **高保真 UI**：Match / Create / Transfer / Discuss 四栏 + 绿底 `OK` 按钮 |
| **Match：部分匹配 & 尾差调整** | 支持 Split 部分付款 + **Minor Adjustment** 调尾差 | **不支持**！[reconcile.py](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/app/reconcile.py#L480-L481) 硬校验 `if total != need: raise LedgerError("勾对金额必须等于流水金额")`，**不能部分匹配，不能调手续费/尾差** | **完整支持**：多选匹配、部分核销、**Minor Adjustment（直接调尾差进 `860 Rounding` 等科目）** |
| **Match：匹配发薪/手工/已有付款** | 支持匹配 Payment / Spend / Receive / Transfer / Payroll | **支持**：`unmatched_journals` 可匹配 `TRANSFER`、`PAYROLL`、`MANUAL` 分录上的银行行 | 支持匹配发票/账单、已有 Payment、以及 `MATCH_TRANSFER` 互转交易 |
| **Create（直接编码）** | 支持多行拆分（Split）与含税模式 | **仅单行单科目单税码**（`code_statement` 不支持拆成两行不同费用/税码） | **支持多行拆分**、`INCLUSIVE`/`EXCLUSIVE` 切换及反向税额正确扣减 |
| **Transfer（跨行互转防重）** | Bank A 转出后，Bank B 导入流水中自动推荐匹配，不双倍记账 | **已实现防重**：`transfer_statement` 会扫描 `unmatched_journals` 中的 `TRANSFER` 分录匹配并置 `created_here=0`，避免双边重复过账 | **已实现防重**：Bank 2 自动推荐 `MATCH_EXISTING_TRANSFER` + `MATCH_TRANSFER`，[test_04](file:///D:/ai-work/au-faiw/xero调研/app/backend/tests/test_04_audit_fixes_and_lifecycle.py#L265-L318) 实测通过 |
| **Discuss 备注** | 持久化保存到交易记录与审计轨迹 | **仅内存假表单**：`static/app.js` 第 822 行明写 *"Notes stay on this screen until you leave the page"*，切换页面即丢失 | 随对账/流水记录持久化 |
| **Bank Rules（银行规则）** | Spend/Receive/Transfer 规则；ALL/ANY 多条件；**固定金额 + 百分比拆行** | **极简规则**：仅单条 `contains` + 可选精确金额 + 单科目/税码；`auto_apply` 逻辑较好（会优先让路给唯一 Match！）；**无编辑入口、无多条件、无拆行** | **完整规则引擎**：Spend/Receive/Transfer 规则、**ALL/ANY 多条件**、**Fixed + Percent 多行拆分**、支持新增/编辑（`PUT`）/删除 |
| **Cash Coding（批量网格）** | 批选后一次 `Save & Reconcile All` 原子提交 | `Cash coding` Tab 本质是**逐行独立小表单**（每行一个 `OK` 按钮单条提交，不支持多选批改与一键批提交） | **完整批处理网格**，一次 `POST /cash-coding/apply` **单事务原子提交**（已通过冲突回滚测试） |
| **Unreconcile vs Remove & Redo** | 区分“仅解绑”与“彻底冲销重做” | **混为一谈且物理删库**：只有 `Unreconcile` 按钮，且内部通过 `void_journal` **物理 `DELETE`** 掉分录/付款/交易（若另一侧银行还连着同一笔 Transfer 会拦截报错） | **严格区分** `Unreconcile` 与 `Remove & Redo`：全部走**不可变冲销凭证**（且 Remove & Redo 会连带冲销 Minor Adjustment 尾差及重开双边互转） |

---

### 模块 6：总账、手工凭证与会计师控制工具（Accounting & GL Controls）

#### 6.1 三方能力与源码深度对比
| 对比项 | 真实 Xero AU | FINOVA（`db.py` / `seed.py` / `posting.py`）`[双方源码实证]` | LedgerFlow AU（`accounting_core_sqlite.sql` / `ledger.py` / `manual_journals.py`）`[双方源码实证]` |
|---|---|---|---|
| **AU 标准科目数量** | ~50+ 标准科目 | **36 个 AU 科目**（最新 `seed.py` 已补全 310/404/469/477/478/630/804/825/826/860/960 等） | **54 个 AU 科目** |
| **总账不可变防线** | 物理不可篡改，纠错必出反转分录 | **严重漏洞**：无触发器；`void_journal` 直接执行 **`DELETE FROM journal_line` 与 `DELETE FROM journal`**；无 `audit_logs` 表 | **6 个 SQLite `BEFORE UPDATE/DELETE` 触发器**物理锁死 `journals`、`journal_lines`、`audit_logs`（经 [test_01](file:///D:/ai-work/au-faiw/xero调研/app/backend/tests/test_01_db_triggers_and_money.py#L17) 验证触发 `LEDGER_IMMUTABLE` 拦截） |
| **Manual Journals（手工凭证）** | 47 受控科目过滤、Draft/Posted/Void/Edit、含税、Auto-Reverse、Cash Basis | `manual_journal` 仅校验借贷相等与>=2行：**无 Draft/Void/Edit、无含税模式、无 Auto-Reverse、`journal_line` 无税码列、未过滤 `610/800/090/820` 系统科目** | **完整实现**：**47 可选科目严格屏蔽系统控制科目**、Draft/Posted/Void、Posted 编辑（逆向冲销重记）、**含税模式与借贷双向正负号**、**Auto-Reversing** 次月自动冲回、`showOnCashBasis` |
| **Tracking Categories** | 最多 2 组维度 | **未实现** | **已实现**（最多 2 组，挂载行项目并联动 P&L/Find & Recode） |
| **Conversion Balances** | 期初余额与 `840` 轧差 | **未实现** | **已实现**（平衡校验 + `840 Historical Adjustment` 轧差） |
| **Find and Recode** | 批量重分类科目/税码/Tracking | **未实现** | **已实现**（Adviser 批量重分类科目与 Tracking 1，且已修复未付单据污染 Cash P&L 漏洞；暂不支持批量改 Tax Rate） |
| **Assurance & Audit Log** | 防舞弊看板 + 全量审计日志 | **未实现** | **已实现**（Assurance 看板 + 物理不可变 `audit_logs`） |

---

### 模块 7：财务报表与经营分析（Reporting & Analytics）

#### 7.1 三方能力与源码对比
* **相同点**：双方均坚持“报表直接由总账分录 `SUM` 聚合，不另存第二套账”，且均提供了 Trial Balance、Profit & Loss、Balance Sheet、Aged Receivables/Payables 与 Account Transactions。
* **核心差异（通过读 FINOVA `app/reports.py` 发现的重要限制）**：
  1. **日期范围筛选缺失（FINOVA）**：FINOVA 的 [reports.py](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/app/reports.py#L82-L138) `reports(conn, org_id)` **没有任何日期参数**——P&L、BS、TB 全部按数据库全历史汇总，会计师无法查看“上季度利润表”或“去年 6 月 30 日资产负债表”；LedgerFlow AU 所有报表均支持精准日期区间或截止日查询。
  2. **Cash Basis P&L（收付实现制损益）**：FINOVA **不支持**；LedgerFlow AU 完整支持 Accrual / Cash 双口径切换，且支持 Tracking 过滤。
  3. **跨财年虚拟结转 & 负银行重分类**：FINOVA **不支持**（`090` 银行负余额直接以负数展示在资产侧）；LedgerFlow AU 在 BS 中完整实现了跨财年损益自动滚入 `960 Retained Earnings` 与负银行透支自动重分类为流动负债（`Overdraft`）。
  4. **现金流预测 & CSV 导出**：LedgerFlow AU 实现了 Short-term Cash Flow（7/30/90 天预测）及 P&L/BS/TB/Aged/BAS 全表 CSV 导出；FINOVA 均无。

---

### 模块 8：澳洲税务与申报准备（AU Tax: GST / BAS / TPAR）

#### 8.1 三方能力与源码深度对比
| 对比项 | 真实 Xero AU | FINOVA（`app/tax.py` / `app/seed.py`）`[双方源码实证]` | LedgerFlow AU（`services/bas.py` / `ReportsAndBasView.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **预设税率** | 11 项 ATO 标准税码 | **6 项**（OUTPUT/INPUT/EXEMPTOUTPUT/EXEMPTEXPENSES/EXPORTOUTPUT/BASEXCLUDED） | **11 项**（额外包含进口/资本采购/进项免税 `GSTONIMPORTS`/`CAPEXINPUT`/`GSTONCAPIMPORTS`/`EXEMPTCAPITAL`/`INPUTTAXED`） |
| **自定义税率新建** | 支持 | **已实现**（`POST .../tax-rates`，可新增如 `CUSTOM 5%` 并在开票使用） | **暂不支持** |
| **BAS 箱体覆盖** | Simpler BAS + Full BAS | **Full BAS + Simpler BAS 全箱体**：`G1, G2, G3, G5, G6, G10, G11, 1A, 1B, W1, W2, Box 9, ATO应付` | **Simpler BAS + `G10/G11`**：`G1, G10, G11, 1A, 1B, 8A, 8B, Payment 9`；**缺 `G2, G3, G5, G6, W1, W2`** |
| **G1 含税/不含税 & 整元取整** | 支持 G1 Incl/Excl 配置 + Whole Dollar | `G1` 固定取净额（Excl GST）；全表以两位小数（cents）展示，无 Whole Dollar 取整 | **支持 `G1` `INCLUSIVE`/`EXCLUSIVE` 切换 + ATO Whole Dollar 整元取整** |
| **Cash Basis（收现制）BAS 准确性** | **按收付款日期与收款比例分摊** | **存在源码级逻辑缺陷**：<br>1. [tax.py#L100-L107](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/app/tax.py#L100-L107) 用 `EXISTS (SELECT 1 FROM payment ...)` 抓出整张单据后直接加总**全单 `net_cents`**（跨期部分收款会**重复计入整单销售额**！）；<br>2. [tax.py#L114-L126](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/app/tax.py#L114-L126) `_gst_in_period` 按 `j.date` 查 `820`，**完全忽略 `gst_basis='Cash'`——导致 Cash BAS 下 `1A/1B` 实际按发票日（Accrual）计算！** | **严格准确**：按实际付款日期与付款比例 `cash / total` 逐行拆算 `G1/G10/G11/1A/1B`，已通过部分收款与 Cash Credit Note 核销/退款测试 |
| **1A/1B 取数来源与反向处理** | 按税码与方向精确扣减，不轧差 | 直接 `SUM(credit)` / `SUM(debit)` 科目 `820`（若出现手工调账或冲销，借方销项可能串入 `1B`） | 基于 `journal_lines.tax_type_code` + 方向符号函数计算，**已通过反向含税 MJ 与反向银行收支验证** |
| **Worksheet / Audit / TPAR** | 完整提供 | **均有独立菜单页**（多期 `Activity statements` 列表、GST calculation worksheet、GST audit、**TPAR 承包商年报**） | BAS 页内嵌 **Transactions by Tax Rate 汇总表 + GST Audit Report 逐笔明细 + CSV 导出**；**无 TPAR**，无独立 G1-G20 Worksheet 页 |
| **定稿与回溯补报（Unfiled）** | Finalise 水位线冻结 + 下期追补 Unfiled | `OPEN -> PREPARED -> FILED` 状态流转；**无水位线机制**，已 Filed 期间后再补单会悄然改变历史期间数字 | **完整实现 `Finalise` 水位线（`max_journal_number`）与下期自动高亮追补 `Unfiled amounts`** |

---

### 模块 9：澳洲薪酬管理（Payroll AU & STP）

#### 9.1 三方能力与源码对比
| 对比项 | 真实 Xero AU | FINOVA（`app/payroll.py`）`[双方源码实证]` | LedgerFlow AU（`ContactsAndSettingsView.tsx`）`[双方源码实证]` |
|---|---|---|---|
| **实现程度** | 完整企业级 Payroll + STP2 | **最小可用闭环**：员工、年病假、工时表、Pay Run（Draft→Posted）、Super 汇总、STP 页面 | **Stage 2 占位页**，引导查看 `477/478/804/825/826` 实时总账余额 |
| **工时与休假精度** | 支持小数小时（如 7.5h）与完整累计规则 | `db.py` 中 `hours`、`annual_leave_hours`、`sick_leave_hours` 全为 **`INTEGER` 整数**，不支持半小时假或小数工时 | 未实现 |
| **PAYG & Super 算法** | ATO PAYG 个人所得税阶梯表 + SuperStream | PAYG 为**组织统一百分比（默认 15%）**，Super 默认 12%，按人四舍五入后汇总 | 未实现 |
| **发薪过账科目路径** | `Cr 804 Wages Payable` 过渡，银行出款后核销 `804` | **跳过 `804`（尽管 `seed.py` 建了 `804`），直接 `Cr 090 银行净额`**（并可在银行对账里用 `unmatched_journals` 匹配 `PAYROLL` 分录）；无 Pay Run 撤销/作废 | 预留 `PAYROLL` 枚举与 `804` 等全部科目 |
| **BAS W1 / W2 联动** | 自动汇总进 Activity Statement | **已打通**：按已过账 `pay_run.payment_date` 自动归集至 BAS `W1` 与 `W2` | 暂缺 `W1 / W2` |

---

### 模块 10：重资产与外围扩展域（Fixed Assets / Projects / Expenses / App Store）

* **相同点**：双方现阶段均未实现 Fixed Assets 自动折旧台账、Projects 工时预算盈亏、Expense Claims 员工垫付报销流以及 App Store 真实 OAuth 集成。
* **差异点**：FINOVA 在产品导航中完全省去了这 4 个域；LedgerFlow AU 依据 Xero 全站产品地图设立了规范的 **Stage 2 占位页**、替代操作指引（如用 2D Tracking 替代 Projects、用 Bills/Spend Money 替代报销）以及对应总账活科目实时余额读取，并预置了 `connected_apps` 表骨架。

---

### 模块 11：组织设置、权限体系与锁账控制（Settings, RBAC & Lock Dates）

* **相同点**：均针对澳洲默认配置（`AUD`、财年 `30 June`）实现了组织细节、单据前缀、GST 期间与基础设置，并提供测试账套 Reset 能力。
* **核心差异**：
  - **FINOVA**：`settings` 页还承载了 `Default sales/purchase account & tax`、单据默认含税设置及薪酬日历/费率，但**没有 `users` 表、没有 RBAC 权限区分、没有 Soft/Hard Lock Dates 锁账控制**。
  - **LedgerFlow AU**：完整实现了 **3 级角色模型（`ADVISER` / `STANDARD` / `READONLY`）与双层锁账（Soft Lock 放行 Adviser / Hard Lock 全员拦截返回 `422`）**，前后端联动严密；但当前仍缺乏真实登录认证（`get_actor` 默认取首行用户，`/auth/switch-role` 需在上线前下线）。

---

## 第三部分：横向跨维度深度对比

### 3.1 算税与数据模型对比

| 维度 | FINOVA（`minimal-ledger`） | LedgerFlow AU（`app/`） |
|---|---|---|
| **数据库规模** | **22 张 SQLite 表**（外键开启，**0 个触发器**） | **33 张 SQLite 表 + 6 个触发器**（WAL 模式 + `busy_timeout=5000`） |
| **算税精度** | `*_cents` 整型 + `rate_bp`（万分比），整型 `//` 四舍五入 | `*_cents` 整型 + `TEXT` 单价/税率，**`decimal.Decimal`（`ROUND_HALF_UP`）** 行级算税 |
| **并发与幂等** | 无 `BEGIN IMMEDIATE` 显式写锁声明、无乐观锁、无 `Idempotency-Key` | `BEGIN IMMEDIATE` 原子事务 + **`version` 乐观锁（409）** + **`Idempotency-Key` 载荷哈希校验（409）** |
| **API 契约（`main.py`）** | **34 个路由**（4 `GET` + 30 `POST`），**所有写操作均返回完整全量 `snapshot` JSON** | **84 个标准 REST 路由**（26 核心管理 + 58 业务核算，`GET/POST/PATCH/PUT/DELETE`），按模块按需请求与局部返回 |

> **可维护性与扩展性诊断**：FINOVA 的前端 `static/app.js`（2,299 行原生字符串模板）配合全量 `snapshot` 协议，在单机演示时极度轻便；但随着单账套单据量增长（例如 `Metro Build` 仅 200 张发票已需全量序列化，未来若上千张单据、多并发用户同时操作），每次点击都重算全部财务报表+全期 BAS+全部对账建议并全量下发 JSON，**将出现严重性能瓶颈与写覆盖竞态（Last-Write-Wins）**。LedgerFlow AU 的 REST 分层与乐观锁设计则能直接向 PostgreSQL 多租户 SaaS 演进（上线前主要需补齐 JWT 认证与消除事务前预读 TOCTOU）。

### 3.2 交付物与测试质量实况对比

| 维度 | FINOVA（`minimal-ledger`） | LedgerFlow AU（`xero调研`） |
|---|---|---|
| **文档与资产包** | 极其出色：**4 份图文并茂 PDF**（产品设计文档、用户手册、测试报告、六行业测试分析报告）+ 完整对比截图 + `deploy/` Windows 服务/Caddy 部署脚本 | 极其厚重的工程研究资产：`Xero-Research`（16 域深度研究+DOM/Network 证据）、`Accounting-SaaS-Blueprint`（DDL/OpenAPI/Fixtures）、`MVP-Acceptance-Audit`（8 份独立审计与评审文档）；**缺图文用户手册** |
| **自动化测试覆盖** | 41 项全周期用例 + 42 项银行对账隔离测试 + 6 行业体量矩阵脚本（测试覆盖面广，但多为正向剧本，未测反向税号、部分收款 Cash BAS、不可变删改、跨组织隔离） | 本轮实测 **`pytest` 14 项全通（`14 passed in 6.92s`）**`[已验证]`，高密度覆盖不可变触发器、Golden Fixtures 累加、反向含税 MJ/Bank 符号、双边互转、Remove&Redo 尾差联动、Cash Coding 原子回滚、Cash CN 追补与全生命周期；**缺 Playwright E2E 与并发压测** |

---

## 第四部分：团队评审结论与下一步融合决策建议

### 4.1 给团队的评审结论（怎么看这两套成果？）

1. **FINOVA 是一套“界面还原巧、业务线拉得极宽、交付包装极佳”的原型工程**：它在短短两天迭代里补进了 `Match / Create / Transfer` 对账 UI、36 个科目、6 行业演示和图文报告，非常适合快速演示“Xero 长什么样、记账+发薪+Full BAS+TPAR 怎么串起来”。但**直接用作生产账本存在严重风险**：总账分录可被 `unreconcile` 物理 `DELETE`、Cash BAS 的 `1A/1B` 错按 Accrual 算且部分收款会双倍计税、财务报表不能选日期、没有 Credit Note 与权限锁账。
2. **LedgerFlow AU 是一套“总账内核严密、对账与单据边界扎实、可向商业 SaaS 演进”的工程底座**：物理不可变触发器、行级 `Decimal` 舍入、Credit Note 全状态机、银行 Split/尾差/Remove&Redo、双层锁账、Cross-FY BS 与精确 Cash BAS，都已经过严格审计和自动化回归验证。目前主要差的是**业务广度补全（TPAR / Full BAS 剩余箱体 / 自定义税率）**、**公网认证安全底座**以及**前端工程收尾（URL 路由/响应式/组件拆分）**。

### 4.2 建议从 FINOVA 吸收并落地到 LedgerFlow AU 的 6 项高价值资产

| 优先级 | 可吸收项 | 具体落地做法与预期工作量 |
|---|---|---|
| **P1** | **Full BAS 补全 `G2/G3/G5/G6` 与独立 Worksheet 页** | `bas.py` 已有 `G1/G10/G11/1A/1B` 与 `EXEMPTEXPORT` 映射，补算 `G2/G3/G5/G6` 并激活 `FULL_BAS` 开关（极小工作量，保留 LedgerFlow 精确的 Cash 分摊与整元舍入） |
| **P1** | **TPAR 承包商年报闭环** | `contacts` 增加 `is_contractor` 标记（已有 `abn`），新增 TPAR 按澳洲财年汇总 `ACCPAY` 账单视图与 CSV 导出 |
| **P1** | **自定义税率新增入口** | 开放 `POST /orgs/<org_id>/tax-rates` 接口与 Settings 页面添加税率弹窗 |
| **P1** | **银行对账界面新增 `OK X unique matches` 与 `Find & Match` 快捷流** | 借鉴 FINOVA [finova-recon-match.png](file:///D:/ai-work/au-faiw/xero调研-2/minimal-ledger/docs/images/finova-recon-match.png) 的唯一匹配一键确认交互，提升高频对账效率 |
| **P2** | **图文并茂的《用户操作手册》与多行业测试矩阵** | 借鉴 FINOVA《六个行业测试分析报告》构造餐饮/建筑/出口/零售/诊所/设计 6 套行业验收账套，并产出带截图的团队/客户手册 |
| **P2** | **单机一键部署脚本参考** | 参考 `minimal-ledger/deploy/` 整理标准容器化或本机守护进程部署模板 |

### 4.3 需团队评审会议拍板的 5 个决策议题

1. **【产品边界】TPAR 与 Full BAS（G2/G3/G5/G6）是否立即纳入本阶段补齐？**（建议：**是**，成本极低且能迅速拉齐与 FINOVA 在澳洲税务展示上的差距，同时保持更高精度）。
2. **【Payroll 路线】Stage 2 的 AU Payroll 是走 FINOVA 的“简化固定比例先可用”，还是坚持“对接标准 ATO 税表 + `804` 过渡 + 第三方集成”？**（建议：若面向真实澳洲报税客户，**绝不可上线 15% 固定税率发薪**，应坚持合规税表或生态集成；若仅作内部估算模拟，才可采用简化版并强制标注免责提示）。
3. **【安全底座】何时暂停业务扩展，优先完成 JWT 认证、下线 `switch-role`、TOCTOU 事务收拢与 PostgreSQL/Alembic 迁移？**（建议：**列为下一迭代 P0 红线任务**，阻塞一切对外试运行）。
4. **【前端重构】何时落地 `react-router-dom` URL 路由、500px 窄屏适配以及 3 个超千行前端巨型组件的拆分？**
5. **【质量门禁】如何补齐 Playwright 浏览器端到端回归测试，防止后续加功能破坏现有 14 项核心账务防线？**
