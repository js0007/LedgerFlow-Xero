# MVP 核心业务模块详细实施规格（Module Specifications）

> **用途：** 为 AI Coding Agent 提供各业务模块精确的状态机、边界保护与 UI-to-API 行为约束。

---

## 模块 1：Chart of Accounts & Tax Rates（科目表与税率保护）

1. **建账默认种子（AU 54 科目 + 6 Active / 5 Archived 税率）：**
   - 直接加载标准化种子文件 [au-seed-data.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/schemas/au-seed-data.json) 植入 54 个默认 AU 科目与 11 条 AU 税率（对齐 [E04-au-default-coa.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/dom/E04-au-default-coa.json) 与 `E06-NET`）。
   - 系统保护拆分为两个正交标志（`E29-NET` 实证）：
     - **`isSystemLocked = true`（防删除/防归档）：** 包含 `497`, `498`, `610`, `630`, `800`, `801`, `804`, `820`, `825`, `826`, `840`, `850`, `860`, `877`, `960`；禁止删除/归档（返回 `422`）或修改 `system_account`。
     - **`manualJournalExcluded = true`（禁止手工凭证直接借贷，47/54 过滤）：** 仅排除 **`497, 498, 610, 630, 800, 801, 877`** 与所有 `BANK` 科目；保留其余 47 科（含 `804, 820, 825, 826, 840, 850, 860, 960`）可在 Manual Journal 中选择。
2. **TaxRate 校验：**
   - 任何单据行（Invoice / Bill / BankTransaction / ManualJournal）保存或过账前，服务端查验 `tax_rate.status == 'ACTIVE'` 且对应 `account.account_class` 在 `tax_rate.can_apply_to_*` 中为 `true`（如 `OUTPUT` 不允许选在 Expense 科目上；`INPUT` 不允许选在 Revenue 科目上）。

---

## 模块 2：Manual Journals（手工日记账）

1. **受控科目隔离：** `GET /accounts?forManualJournal=true` **必须**精确过滤掉 `manual_journal_excluded = true`（`497, 498, 610, 630, 800, 801, 877`）与所有 `account_type = 'BANK'` 的科目（返回 47 个可选科目）；`POST /manual-journals` 服务端再次强校验拒绝，防止前端绕过。
2. **Tax 模式、期间锁校验与不平衡拦截：**
   - 选择 `NO_TAX` 时，所有明细行 `tax_rate` 自动锁为 `BASEXCLUDED` (`0%`)；若 `SUM(debit) != SUM(credit)` 返回 `422`；若命中 Hard Lock Date 返回 `400/422 PERIOD_HARD_LOCKED`（`E37-PAGE`）。
   - 选择 `EXCLUSIVE` / `INCLUSIVE` 时，允许各行选择适用税码；借方税额记入 `820 GST` 借方（`INPUT` 进入 `1B`），贷方税额记入 `820 GST` 贷方（`OUTPUT` 进入 `1A`）。
3. **Auto-reversing Date：** 若填写 `auto_reversing_date`（必须 `> journal_date`），在 `Post` 同一事务内立即生成第二张日期为 `auto_reversing_date` 的完全逆向分录（`source_type = 'MANJOURNAL_REVERSAL'`，Narration 自动加 `Reversal: ` 前缀并双向关联 `parent_manual_journal_id`），保证未来期自动抵消且跨期锁账安全。

---

## 模块 3：Invoices, Bills & Credit Notes（应收应付单据）

1. **状态机与编辑权限：**
   - `DRAFT` / `SUBMITTED`：允许任意修改金额、删除、**0 总账影响**。
   - `AUTHORISED`（Approve）：原子生成 `ACCREC` / `ACCPAY` 分录；一旦进入 `AUTHORISED`，若已有收付款（`amount_paid > 0`），禁止直接 `Void`，前端仅显示 `Create Credit Note`。
   - `VOIDED`：仅允许在 `amount_paid == 0 && amount_credited == 0` 且日期未锁账时执行，**通过写入 `ACCREC_REVERSAL` / `ACCPAY_REVERSAL` 冲销原凭证**，保留凭证连续性。
2. **发票编号（Auto-numbering）与 Credit Note 核销：**
   - Sales Invoice 与 Sales Credit Note 默认共享同一递增序列（如 `INV-0001` → `INV-0002` → `CN-0003`），并发新建时在提交/批准前检查唯一约束。
   - 批准 Sales Credit Note 且客户存在未结清发票时，引导至 `Allocate Credit` 界面；全额分配后 `Credit Note` 状态置 `PAID`（`RemainingCredit = 0.00`）并同步推进目标发票 `amountCredited` 与 `PAID` 状态（`E33-PAGE`）。
   - Purchase Bill 默认采用 `Tax inclusive` 录入，批准后详情视图归一化展示净单价与明细税额（`Tax Exclusive` 口径，`E32-PAGE`）。

---

## 模块 4：Bank Reconciliation & Cash Coding（银行对账与快捷编码）

1. **CSV 导入与防重：**
   - 支持标准头 `*Date,*Amount,Payee,Description,Reference,Cheque Number`（直接兼容 [E22-mvp-bank-statement.csv](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E22-mvp-bank-statement.csv)）。
   - 每行生成确定性 SHA-256 `import_hash`（基于 `bank_account_id + tx_date + amount + payee + description + reference + 行序号防同日同额两笔真交易碰撞`，提示：同文件内两笔相同行按行内出现计数 `occurrence_idx` 区分，**既防重复导入同一份文件，又不误杀同一天两笔一模一样的 110.00 收款！**）。
2. **Suggestions 匹配算法（MVP 精确+容差规则）：**
   - 入账行（`amount > 0`）优先匹配 `invoice_type = 'ACCREC'` 且 `status = 'AUTHORISED'` 且 `(total - amount_paid - amount_credited) == amount`（精确相等，或容差日期 ±30 天内且 Reference/Contact Name 命中优先排序）。
3. **双动作过账：**
   - **`MATCH_INVOICE`（场景 2）：** `SELECT ... FOR UPDATE` 锁定银行行与发票 -> 创建 `Payment` (`Dr Bank / Cr 610 AR`) -> 更新发票 `amount_paid += amount`（全额结清自动置 `PAID`）-> 置银行行 `RECONCILED`。
   - **`CREATE_BANK_TX`（场景 3 & Cash Coding）：** 按 `taxMode`（默认 `INCLUSIVE`）逐行计算净额与税额 -> 写入 `bank_transactions` (`RECEIVE`/`SPEND`) -> 生成 `CASHREC`/`CASHPAID` 分录 (`Dr Bank / Cr 200 Sales & Cr 820 GST`) -> 置银行行 `RECONCILED`。
   - **Twin Balances 公式：**
     - `statement_balance = SUM(bank_statement_lines.amount)`
     - `book_balance = SUM(journal_lines WHERE account_id = bank_account_id THEN debit_amount - credit_amount)`
     - `difference = statement_balance - book_balance`（`unreconciled_count == 0` 时若无手工开账差则 `difference == 0`）。
