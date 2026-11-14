# Xero 与 ATO 官方文档核心规则摘要（Official Sources Digest）

> **用途：** 为 `Xero-Research` 与 `Accounting-SaaS-Blueprint` 提供 `[Documented]` 官方规则基准，并与真实网页抓包证据（`E01`–`E28b`）交叉验证。  
> **核对日期：** 2026-11-14

---

## 1. Australian Taxation Office (ATO) — GST & Simpler BAS (`ato.gov.au`)

1. **Simpler BAS 适用门槛与申报栏位 (`[Documented]` ATO Simpler BAS Reporting):**
   - 适用于 GST 年营业额低于 **\$10 million AUD** 的澳大利亚企业（营业额 >= \$10M 须采用 Full BAS）。
   - Simpler BAS **只需填报 3 个核心 GST 字段**：
     - **`G1`（Total sales）**：当期总销售额（在 ATO 与 Xero 默认规则下可选择含 GST 或不含 GST 填报，须与系统设置一致；Xero AU Simpler BAS 默认以 **GST inclusive / `totalGross`** 呈现 `G1` — 与 `E20-NET` / `E28-NET` 实测一致）。
     - **`1A`（GST on sales）**：当期销项 GST 总额。
     - **`1B`（GST on purchases）**：当期可抵扣进项 GST 总额。
   - **免填字段（Simpler BAS 不需向 ATO 逐项汇报）：** `G2`（出口销售）、`G3`（其他免 GST 销售）、`G10`（资本性采购）、`G11`（非资本性采购）；但在企业会计系统内部仍保留对应税码与明细分类以便审计与切换 Full BAS。
2. **BAS 会计核算口径（Cash vs Accruals）(`[Documented]` ATO GST Accounting Methods):**
   - **Accruals（权责发生制）：** 按**发票/账单签发或收到的日期**确认 `G1 / 1A / 1B`（无论是否已收付款）。
   - **Cash（收付实现制）：** 仅在**实际收到客户款项或实际支付供应商款项的日期**按比例确认 GST（部分收付款按收付比例拆分税额）。
   - 一般 GST 年营业额低于 \$10M 的小型企业可选择 Cash Basis。
3. **BAS 金额取整 (`[Documented]` ATO BAS Whole Dollars):**
   - BAS 表向 ATO 申报的各字段金额一般取**整数澳元（Whole dollars）**（去掉分，不做银行家四舍五入进位至分以上；具体以 ATO 当期填表指引为准，实测 Xero BAS 接口与 UI 均输出整数字符串 `g1Total: "220"`, `oneATotal: "3730"`）。

---

## 2. Xero Central 会计与税务核心规则 (`central.xero.com`)

1. **单据 GST 舍入规则（Line-by-Line Rounding）(`[Documented]`):**
   - Xero 对每张 Invoice / Bill / BankTransaction 按**逐行（line-by-line）**计算税额并四舍五入至 **2 位小数**，再将各行汇总得出整单 Tax 与 Total（而非先加总小计再统一算税）。
   - **Tax Exclusive：** `line_net = qty * unit_price * (1 - discount)`；`line_tax = round(line_net * rate, 2)`；`line_gross = line_net + line_tax`。
   - **Tax Inclusive：** 从含税单行总额倒算税额（AU 10% GST 下为 $T = \text{round}(G / 11, 2)$），再得出 `line_net = line_gross - line_tax`。
   - 若外部客户系统采用整单算税导致 1 分钱差异，可通过手工微调税额行或使用 `860 Rounding` / 核销微调处理。
2. **系统控制科目与手工日记账限制（System Accounts & Manual Journals）(`[Documented]`):**
   - 为防止破坏子账（Subledger）与银行对账一致性，Xero 的 `Manual Journals` 禁止直接选择以下受控/系统科目：`610 Accounts Receivable (DEBTORS)`、`800 Accounts Payable (CREDITORS)`、`Bank` 银行账户、`960 Retained Earnings` 等。
   - 若需调整 AR/AP，必须通过对应联系人的 Invoice / Credit Note / Bill；若需调整银行余额，必须使用 Spend Money / Receive Money 或通过清算科目（Clearing/Suspense Account `850`）中转。
3. **Conversion Balances 期初开账与差额处理 (`[Documented]`):**
   - 录入历史开账余额后，Xero 要求：
     - `Accounts Receivable` 期初总余额 **必须精准等于** 转换日前所有未结历史销售发票（或借项）的汇总；
     - `Accounts Payable` 期初总余额 **必须精准等于** 转换日前所有未结历史采购账单汇总；
     - 借贷总差额在试算配平前由系统自动挂入 `840 Historical Adjustment` 科目；一旦试算平衡，Historical Adjustment 为 0。
4. **Lock Dates 双层锁账 (`[Documented]` & `[Observed]` `E03-PAGE`):**
   - **层 1（Stop all users except advisers）：** 阻止 Standard / Invoice Only 等普通用户在该日期及之前过账或修改单据，但允许 **Adviser（会计师/顾问）** 调整与过账，并允许自动化对账。
   - **层 2（Stop all users, including advisers）：** 硬锁，彻底冻结历史期间的财务变动，任何角色均无法在此日期及之前写入新凭证或修改原单据，除非管理员显式解除锁账（操作记录入 `History & Notes`）。
5. **Void vs Credit Note 差异 (`[Documented]`):**
   - **Void（作废）：** 仅当单据处于 `DRAFT` / `SUBMITTED` 或尚**未关联任何 Payment / Credit Note** 的 `AUTHORISED` 状态时允许，作废后不保留有效应收/应付及税额（实测已过账总账通过冲销分录抵消或标记作废）。
   - **Credit Note（贷项通知单）：** 当原发票/账单已部分或全额付款、或已向客户发出且需要保留正式退货/折让凭证链时使用，产生逆向收入/费用与逆向 GST（减少 `1A` 或 `1B`）。

---

## 3. Xero Developer — Accounting API 契约规则 (`developer.xero.com`)

1. **核心端点的 `LineAmountTypes` 与默认值 (`[Documented]`):**
   - 支持枚举：`Exclusive`、`Inclusive`、`NoTax`。
   - **默认差异：** `Invoices` / `CreditNotes` / `PurchaseOrders` 未传时默认 `Exclusive`；`BankTransactions`（Spend/Receive Money）未传时默认 `Inclusive`。
2. **`Journals` vs `ManualJournals` 隔离设计 (`[Documented]`):**
   - **`GET /Journals`（只读总账流水）：** 记录系统内一切已过账业务自动生成的复式分录；每个 Journal 拥有单调递增序号 `JournalNumber` 与 `SourceType`（`ACCREC` 销售发票、`ACCRECCREDIT` 销售贷项、`ACCPAY` 采购账单、`ACCPAYCREDIT` 采购贷项、`CASHREC` 银行收款、`CASHPAID` 银行付款、`TRANSFER` 转账、`MANJOURNAL` 手工分录等）。分录行金额在 API 中用单符号 `NetAmount`（**正数为 Debit，负数为 Credit**）表达。
   - **`GET/POST /ManualJournals`（读写手工分录）：** 仅操作人工调账凭证，支持 `Draft` / `Posted` / `Voided` / `Deleted` 及 `ShowOnCashBasisReports`。
3. **`TaxType` 与 `SystemAccount` 属性 (`[Documented]`):**
   - 行级未传 `TaxType` 时，自动继承所选科目在 COA 中的默认 `TaxType`（AU 常见编码：`OUTPUT`、`INPUT`、`EXEMPTOUTPUT`、`EXEMPTEXPENSES`、`BASEXCLUDED`、`GSTONIMPORTS`）。
   - `Accounts` 模型中系统账号通过 `SystemAccount` 字段区分（`DEBTORS`、`CREDITORS`、`GST`、`BANKCURRENCYGAIN`、`RETAINEDEARNINGS` 等）。
4. **OAuth 2.0、限流与增量同步规范 (`[Documented]`):**
   - **OAuth 2.0：** Short-lived Access Token 有效期 **30 分钟**，配合 Rotating Refresh Token 与租户头 `xero-tenant-id`。
   - **Rate Limits（单租户/单应用）：** **60 calls / minute**（滚动窗口）、**并发 5 请求**、**5,000 calls / day**（Starter 为 1,000）；应用全局上限 **10,000 calls / minute**。超限返回 `HTTP 429` + `Retry-After`、`X-MinLimit-Remaining`、`X-DayLimit-Remaining`。
   - **增量同步：** 强烈建议在 `GET` 查询中携带 `If-Modified-Since` HTTP 头结合 `page` 分页及 Webhooks 事件通知，降低轮询压力。
