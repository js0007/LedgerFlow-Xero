# E29–E38 扩展闭环实测与边界调研轨迹（AU, AUD, `!W5gW!`）

> **测试组织：** `Southern Cross Office Supplies Pty Ltd` (`!W5gW!`, `<ORG_UUID>`) — AU 试用账套（在 [E24-mvp-3scenarios-trace.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E24-mvp-3scenarios-trace.md) 3 笔 MVP 基础数据之上累积执行）  
> **执行时间：** 2026-11-14 ～ 2026-11-15  
> **关联证据：** `E29-NET`, `E29-PAGE`, `E30-PAGE`, `E31-PAGE`, `E32-PAGE`, `E33-PAGE`, `E34-PAGE`, `E35-PAGE`, `E36-PAGE`, `E36-NET`, `E37-PAGE`, `E38-PAGE`

---

## 1. 手工凭证（Manual Journal）47/54 科目差集与自动冲销（`E29`）

- **COA 差集核对（`E29-NET`）：**
  - 默认 AU COA 非银行科目共 **54** 个（`E04-COA`），Manual Journal BFF `/accounts/organisations/<ORG_UUID>` 实际返回并允许选择的科目仅 **47** 个（不含新增的 `BANK` 类银行账户）。
  - **精确排除的 7 个非银行默认科目（`exactExcludedFromDefault54`）：**
    - `497` Bank Revaluations（Expense）
    - `498` Unrealised Currency Gains（Expense）
    - `610` Accounts Receivable（Current Asset）
    - `630` Inventory（Inventory）
    - `800` Accounts Payable（Current Liability）
    - `801` Unpaid Expense Claims（Current Liability）
    - `877` Tracking Transfers（Current Liability）
  - **仍保留可选的常见系统/负债类科目实测：** `804` Wages Payable - Payroll、`820` GST、`825` PAYG Withholdings Payable、`826` Superannuation Payable、`840` Historical Adjustment、`850` Suspense、`860` Rounding、`960` Retained Earnings 均在 47 个可选科目中。
- **自动冲销（Auto-Reversing Journal）实测（`E29-PAGE`）：**
  - 输入：Narration `Prepaid Rent Accrual Adjustment (Auto-Reverse Test)`，Date `14 Nov 2026`，Auto-reversing date `1 Dec 2026`，Tax `No tax`，`Show journal on cash basis reports = true`，Dr `469 - Rent` `100.00` / Cr `850 - Suspense` `100.00`，点击 `Post`。
  - 结果：主凭证 `#5`（`2026-11-14`）过账同时，系统**同步生成**冲销子凭证 `#4`（`2026-12-01`），Narration 自动加前缀 `Reversal: Prepaid Rent Accrual Adjustment (Auto-Reverse Test)`，方向相反（Cr `469 - Rent 100.00` / Dr `850 - Suspense 100.00`），状态为 `Posted` 并通过 `parentManualJournalID` 双向关联。

---

## 2. 期初转换余额与用户角色 RBAC 权限矩阵（`E30`–`E31`）

- **Conversion Balances（`E30-PAGE`）：** `/Accounts/ConversionBalances.aspx` 页面展示以 `Conversion Date` 为界录入选定资产/负债/权益科目余额，自动以 `840 - Historical Adjustment` 轧平试算借贷差；底部连接 `Lock Balances` / Comparative Balances 录入入口。
- **用户权限矩阵（`E31-PAGE` & `!W5gW!` 用户升级实测）：**
  - `/app/!W5gW!/settings/user-access` 展示 **9 种业务角色：** `Subscriber`、`Administrator`、`Standard`、`Payroll admin`、`Invoice only`、`Expenses`、`Read only`、`Project admin`、`Projects standard`。
  - **关键发现：** 新建 AU 试用账套时，组织创建者（Subscriber）在组织业务层默认分配的是 **`Standard`** 角色而非 `Administrator`，因此默认对 `Lock dates`、`Cash coding`、`Publish reports` 无编辑权，必须在 User Access 中手动升级为 `Administrator`（Accounting: Full access）后才解锁 `FinancialSettings.aspx` 的 Lock Dates 输入框。

---

## 3. 采购账单（Bill）含税录入转未税展示与 AP 过账（`E32`）

- **输入（`AccountsPayable/Edit.aspx`）：** Supplier `AusPost Office Supplies`，Date `14 Nov 2026`，Due Date `21 Nov 2026`，Reference `BILL-0001`。AU 默认采购税设置（`Financial Settings -> Tax Defaults -> For Purchases`）为 **`Tax inclusive`**；录入 1 行 `461 - Printing & Stationery`，Tax `GST on Expenses` (`10%`)，Unit Price `110.00`（含税），点击 `Approve`。
- **实测结果（`E32-PAGE`）：**
  - 批准后跳转到 `View.aspx?invoiceID=<UUID>&approved=true`，系统自动将明细单价折算归一化展示为 `Tax Exclusive`（`Unit Price 100.00`，`Subtotal 100.00 + GST 10% 10.00 = TOTAL 110.00`，Status `Awaiting Payment`）。
  - GL 过账：Dr `461 Printing & Stationery 100.00` + Dr `820 GST 10.00` / Cr `800 Accounts Payable 110.00`。

---

## 4. 销售发票 #2 + 部分收款 + 贷项通知单及核销（`E33`）

- **Step 4.1 发票 #2：** 创建并批准 `INV-0002`，客户 `Acme Customer Pty Ltd` (`ACP`)，Date `14 Nov 2026`，Due Date `22 Nov 2026`，Ref `EXT-CREDIT-TEST`，`Tax exclusive`，`1 x 100.00` -> `200 - Sales` (`GST on Income`)，`Subtotal 100.00 + GST 10.00 = Total 110.00`。
- **Step 4.2 部分收款（Partial Payment）：** 在 `INV-0002` 记录收款 `55.00`，Date `14 Nov 2026`，Paid To `Business Operating Account`（下拉同时包含启用了 `enablePaymentsToAccount` 的科目 `880`、`881`、`970`），Ref `PART-PAY-55`。实测 `INV-0002` 状态仍为 `Awaiting Payment`，展示 `Paid: 55.00 | Due: 55.00`，银行账面余额由 `220.00` 升至 `275.00`（未对账差额 `55.00`）。
- **Step 4.3 销售贷项通知单（Sales Credit Note）与自动核销：**
  - 新建 Credit Note 编号自动延续发票序列号 **`CN-0003`**（与 `INV-0001` / `INV-0002` 共用自增序列），Ref `CREDIT-INV-0002`，`Tax exclusive`，`1 x 50.00` -> `200 - Sales` (`GST on Income`)，`Total 55.00`。
  - 点击 `Approve` 后，Xero **自动跳转**至 `/Credits/Allocate.aspx?documentID=<UUID>`（当该客户存在未结清发票时）；输入对 `INV-0002` 核销 `55.00`（Date `14 Nov 2026`），提交后 `CN-0003` 状态变为 `Paid`，`Remaining credit = 0.00`，`INV-0002` 变为 `Paid`（Due `0.00`）（`E33-PAGE`）。

---

## 5. 银行账户交易操作、`Remove & Redo` 与银行规则（`E34`）

- **Bank Transactions 页面（`E34-PAGE`）：** `/Bank/BankTransactions.aspx` 展示 `Balance in Xero: 275.00` vs `Statement balance (14 Nov): 220.00`；`+ New Transaction` 直接提供 Spend Money / Receive Money / Transfer Money 快速创建；选中交易行后顶部 `More` 提供 `Mark as Reconciled` / `Unmark as Reconciled`。
- **`Remove & Redo` 实测：** 勾选 `PART-PAY-55` 点击 `Remove & Redo`，弹出确认框原文：`"permanently remove the 1 selected account transaction? ... for reconciled transactions, this will not delete any statement lines. You can't undo this action."`（实际未确认删除，点击 `Cancel` 保持账套完整性）。
- **Bank Rules（`/app/!W5gW!/bank-rules/create?type=BANKRULETYPE/CASHPAY`）：** 5 步规则引擎：1. 当条件（`Any/All conditions` + 字段 `Payee/Description/Reference/Analysis Code/Amount` + `equals/contains/starts with/is blank`）-> 2. 分配 Contact -> 3. 百分比/固定金额拆行分摊（Allocate fixed values first -> remainder by `%` -> Account + Tax Rate）-> 4. 摘要/参考号来源 -> 5. 规则命名与适用银行账户（单个/全部）。

---

## 6. 总账明细（1071）、报表导出、权责 vs 收付实现制 P&L 及 BAS 对照（`E35`–`E36`）

- **General Ledger Detail (`1071`, `1 Nov – 30 Nov 2026`, `E35-PAGE`)：**
  - 累计 **48 行明细**，Total Debits `815.00` == Total Credits `815.00`。
  - **关键分录实测：** Credit Note 核销（Allocate Credit）会在总账 `610 Accounts Receivable` 产生一组互抵分录（`Dr 55.00` + `Cr 55.00`）。
  - Export 菜单提供 3 种导出格式：**PDF**、**Excel**、**Google Sheets**。
- **Profit & Loss (`1016`, `1 Nov – 30 Nov 2026`, `E35-PAGE`) 口径实测：**
  - **Accrual (`accrualBasis=true`)：** `200 Sales = 250.00`（`100 INV-0001 + 100 Direct Sale + 100 INV-0002 - 50 CN-0003`），Expenses `200.00`（`461 Printing & Stationery 100.00` + `469 Rent MJ #5 100.00`），**`Net Profit = 50.00`**。
  - **Cash (`accrualBasis=false`)：** `200 Sales = 250.00`（因 `INV-0001 110 + Direct Sale 110 + PART-PAY-55 55 + Allocate INV 55 - Allocate CN 55 = 275 含税 / 250 未税`），未付款 `BILL-0001` 退出报表（`461 = 0.00`），而手工凭证 `#5` 因 `showOnCashBasisReports=true` 仍保留（`469 = 100.00`），**`Net Profit = 150.00`**。
- **Simpler BAS Accrual vs Cash 对照（`Oct – Dec 2026`, `E36-PAGE`, `E36-NET`）：**

| 字段 | Accruals BAS | Cash BAS | 实测差因解释 |
|---|---:|---:|---|
| `G1` Total sales | `275` | `275` | Cash 下已收现金 `INV-0001 (110) + Cash Sale (110) + PART-PAY-55 (55) + INV-0002 alloc (+55) + CN-0003 alloc (-55) = 275` |
| `1A` / `8A` GST on sales | `25` | `25` | 同上 |
| `G11` Non-capital purchases | `110` | `0` | 未付款 `BILL-0001 (110)` 在 Cash BAS 下剔除 |
| `1B` / `8B` GST on purchases | `10` | `0` | 同上 |
| `9` Payment amount | **`15`** | **`25`** | 差额 `10` 为未付账单的进项税 |

  - `cash_gst_report_v2` 实测共返回 9 条税基行：包含 Manual Journal `#5`/`#4`（因 `showOnCashBasisReports=true` 进入 `BAS Excluded` 区间），以及 Credit Note 核销生成的正负抵消双行（`CN-0003 -55.00` 与 `INV-0002 +55.00`）。（验证完成后已将 `/bas/settings` 恢复为 `Accrual`。）

---

## 7. 双层锁账期（Lock Dates）实时拦截验证（`E37`）

- **设置（`Setup/FinancialSettings.aspx`）：** 升级用户为 `Administrator` 后，Lock Dates 区域两个日期输入框解锁：
  - Soft Lock（软锁）：`"Stop all users (except advisers) making changes on and before this date. Auto-reconcile still runs during this period."`
  - Hard Lock（硬锁）：`"Stop all users making changes on and before"` -> History & Notes 记录为 `"Lock date (for all users) - added '31 Oct 2026'"`。
- **倒填日期过账拦截实测（`E37-PAGE`）：**
  - 设置 Hard Lock 为 `31 Oct 2026` 后，在 `/app/!W5gW!/journals/create` 尝试提交 `date: "2026-10-15"` 的平衡手工凭证（Dr `469 Rent 50.00` / Cr `850 Suspense 50.00`）。
  - 实测接口 `POST https://manual-journals-bff.xero.com/manualjournals/organisations/<ORG_UUID>` 返回 **`HTTP 400 Bad Request`**：
    - `errors[0].message`: `"The document date cannot be before the end of year lock date, currently set at 31-Oct-2026"`
    - UI 顶部报错：`"This journal date falls in a locked period for your organisation. Choose a different date or check your lock date settings."`
  - （附加观测：提交借贷不平 `50.00` vs `50.01` 时同样拦截：`Total debits (50.00) must equal total credits (50.01)`；测试后已将 Hard Lock 清除为空以保持账套可继续测试。）

---

## 8. P2 周边模块边界速览（`E38`）

- **Products & services (`/app/!W5gW!/products-and-services`)：** 勾选 `Track inventory item` 后：1）弹出限制说明（仅建议 `< 4,000` 个存货 SKU、采用加权平均成本法，且一经发生期初/调整/单据交易不可取消追踪）；2）强制绑定 `Inventory Asset account = 630 - Inventory`；3）`Purchase` 与 `Sell` 复选框强制勾选且禁用取消，`Purchase account` 切换为必填 `Cost of Goods Sold account`（解释了为何 `630` 从手工凭证中屏蔽）。
- **Fixed assets (`/app/!W5gW!/fixed-assets/asset-summary/draft`)：** 新建账套在未调用 `Set start date` 设定固定资产启始财年前，`New asset` 与 `Run depreciation` 按钮处于禁用锁定状态；经典版资产登记与月度批量折旧生成总账凭证与主账联动。
- **Payroll (`/app/!W5gW!/payroll/onboarding`, `E38-PAGE`)：** 虽 AU 默认 COA 已预置 `477/478/804/825/826` 等薪酬过账与清算科目，但 AU Payroll 属于需在 Onboarding 显式点击 `Set up payroll` 激活的子系统（涵盖 Employees、Leave、Timesheets、Pay Run、Superannuation 与 Single Touch Payroll）。
- **Projects (`/app/!W5gW!/projects`)：** 独立项目工时与费用归集视图（All projects / Time entries / Staff time overview / Projects settings），受独立 `Project admin` / `Projects standard` 角色控制。
