# MVP 验收测试基准与核心会计边界测试矩阵（Acceptance & Edge-Case Tests）

> **对标依据：** `调研需求.txt` 第十二章（MVP 三笔业务验收测试） + 干净 Xero 账套 (`!W5gW!`) 实测真值（[E24 轨迹](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E24-mvp-3scenarios-trace.md) & [E29-E38 轨迹](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E29-E38-extended-exploration-trace.md)）。  
> **机器可读种子与自动化测试夹具（Direct Replay Fixtures）：**  
> - **建账初始化种子：** [au-seed-data.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/schemas/au-seed-data.json)（54 默认 AU 科目 + `manualJournalExcluded` 规则 + 11 条 AU 税率）  
> - **端到端回放输入与真值预期：** [mvp-and-extended-fixtures.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/tests/mvp-and-extended-fixtures.json)（严格拆分独立 `suite_1_mvp_baseline` 与累积回归 `suite_2_extended_regression`）  
> **规则说明：** `suite_1_mvp_baseline` 在全新 AU 组织（`AUD`, `30 June` FYE, `Accrual` BAS, `0` 初始余额）中独立执行；`suite_2_extended_regression` 在其后累积回放扩展业务，断言精度为精确 `Decimal` 字符串对比。

---

## 1. MVP 三笔核心业务验收测试场景（必须 100% 通过）

### 场景 1：含税销售发票开具并批准（110.00 AUD, Tax Inclusive 10% GST）
- **输入操作：**
  1. 新建客户 `Acme Customer Pty Ltd`；
  2. `POST /invoices`：`invoiceType=ACCREC`, `issueDate=2026-11-14`, `taxMode=INCLUSIVE`, `line=[desc="Consulting Service", qty="1", unitAmount="110.00", account="200 Sales", taxRate="OUTPUT (10%)"]`, `approveImmediately=true`。
- **强断言（Assertions）：**
  - Invoice `status == 'AUTHORISED'`, `subTotal == "100.00"`, `totalTax == "10.00"`, `total == "110.00"`, `amountDue == "110.00"`；
  - 新增 `Journal #1` (`sourceType = 'ACCREC'`)，且仅包含 3 行（或汇总税行）：
    - `Dr 610 Accounts Receivable`: `110.00`
    - `Cr 200 Sales`: `100.00` (`taxType = 'OUTPUT'`)
    - `Cr 820 GST`: `10.00`
  - 若停在 `DRAFT` 态批准前：`COUNT(journals) == 0`。

### 场景 2：客户银行收款 110.00 AUD 匹配核销发票 #1
- **输入操作：**
  1. 导入银行 CSV（含 `14/11/2026, +110.00, Acme Customer Pty Ltd, Invoice Payment INV-0001` 与场景 3 的 `+110.00` 行）；
  2. 验证未核销前 `Statement Balance = "220.00"`, `Book Balance = "0.00"`；
  3. 对第一条银行流水调用 `POST /reconcile` (`action = 'MATCH_INVOICE'`, 匹配场景 1 发票)。
- **强断言（Assertions）：**
  - 创建 `Payment` (`amount = "110.00"`, `isReconciled = true`)；
  - 发票状态流转为 `PAID`, `amountPaid == "110.00"`, `amountDue == "0.00"`；
  - 新增 `Journal #2` (`sourceType = 'ACCREC_PAYMENT'`)：
    - `Dr Business Operating Account`: `110.00`
    - `Cr 610 Accounts Receivable`: `110.00`
  - **关键防重断言：** `200 Sales` 余额仍为 `Cr 100.00`，`820 GST` 余额仍为 `Cr 10.00`（绝不二次确认收入或税额！）；`Book Balance == "110.00"`。

### 场景 3：银行直接收款 110.00 AUD（Create Receive Money / Cash Coding 编码至 200 Sales）
- **输入操作：**
  - 对第二条银行流水 `+110.00`（`Walk-in Cash Customer`）执行 `POST /reconcile` (`action = 'CREATE_BANK_TX'`, `taxMode = 'INCLUSIVE'`, `account = "200 Sales"`, `taxRate = "OUTPUT (10%)"`)（或通过 Cash Coding 页面等效提交）。
- **强断言（Assertions）：**
  - 创建 `BankTransaction` (`txType = 'RECEIVE'`, `isReconciled = true`, `subTotal = "100.00"`, `totalTax = "10.00"`, `total = "110.00"`)；
  - 新增 `Journal #3` (`sourceType = 'CASHREC'`)：
    - `Dr Business Operating Account`: `110.00`
    - `Cr 200 Sales`: `100.00` (`taxType = 'OUTPUT'`)
    - `Cr 820 GST`: `10.00`
  - 银行对账状态：`Statement Balance == "220.00"`, `Book Balance == "220.00"`, `Unreconciled Lines == 0`。

### 期末总账、四大报表与 BAS 联合验收矩阵（3 笔完成后）

| 验证模块 / 接口 | 预期标准断言值 | 备注与口径说明 |
|---|---|---|
| **Journal Report (`from=2026-11-01, to=2026-11-30`)** | 共 3 张凭证 (`#1, #2, #3`)；总 Debit `"330.00"` == 总 Credit `"330.00"` | 对齐 Xero `E24-PAGE` |
| **Trial Balance (`date=2026-11-30`)** | `Bank` Dr `"220.00"`；`200 Sales` Cr `"200.00"`；`820 GST` Cr `"20.00"`；`610 AR` `"0.00"` | 对齐 Xero `E25-PAGE` |
| **Profit & Loss (`Nov 2026`)** | `Sales = "200.00"`；`Gross Profit = "200.00"`；`Net Profit = "200.00"` | 对齐 Xero `E26-PAGE` |
| **Balance Sheet (`date=2026-11-30`)** | `Total Assets (Bank) = "220.00"`；`Total Liabilities (820 GST) = "20.00"`；`Net Assets = "200.00"`；`Current Year Earnings = "200.00"` | 对齐 Xero `E27-PAGE` |
| **Simpler BAS (`Oct–Dec 2026`, `Accrual`)** | `1A = "20"`；`1B = "0"`；`8A = "20"`；`8B = "0"`；`Payment 9 = "20"` | 对齐 Xero `E28-PAGE` |
| **Simpler BAS `G1 Total sales`** | - 若 `basG1Mode = 'INCLUSIVE'`（Xero 默认）：`G1 == "220"`<br>- 若 `basG1Mode = 'EXCLUSIVE'`（净额口径）：`G1 == "200"` | 需在自动化测试中**同时覆盖双模式用例** |

---

## 2. 关键会计边界与异常回归测试矩阵（Edge-Case Test Suite）

| 用例 ID | 测试场景 | 预期系统行为（Pass Criteria） |
|---|---|---|
| **EDGE-01** | **手工日记账选择受控科目** | `POST /manual-journals` 尝试借/贷 7 个非银行排除科目（`497`, `498`, `610`, `630`, `800`, `801`, `877`）或 `BANK` 科目 -> 必须拒绝返回 `422 SYSTEM_ACCOUNT_LOCKED`，`journals` 表无新增；而 `804/820/840/850/860/960` 等 47 科应正常允许选择（`E29-NET`） |
| **EDGE-02** | **税码与科目类别错配** | 在 `400 Advertising` (Expense) 行强制传入 `OUTPUT`（仅限 Revenue/Asset/Liab） -> 必须拒绝返回 `422 INVALID_TAX_FOR_ACCOUNT` |
| **EDGE-03** | **逐行 GST 舍入（0.01 精度）** | 发票含 3 行 Tax Exclusive：`10.05` (`10% -> 1.01`)、`10.05` (`1.01`)、`10.05` (`1.01`) -> `subTotal=30.15`, `totalTax=3.03`（按行汇总，而非整单 `30.15 * 0.1 = 3.02`） |
| **EDGE-04** | **数据库级总账只增不改防御** | 在测试中尝试直接对 `journal_lines` 执行 SQL `UPDATE` / `DELETE` -> PostgreSQL Trigger 抛出 `42501` 异常拒绝 |
| **EDGE-05** | **Void 已批准发票 vs 已付款拦截** | 未收款 `AUTHORISED` 发票调用 `/void` -> 成功生成 `ACCREC_REVERSAL` 冲销分录，BAS `1A` 归 0；若发票已有 `Payment` (`amountPaid > 0`) 再 `/void` -> 返回 `422 INVOICE_ALREADY_PAID` |
| **EDGE-06** | **两层锁账日期（Soft vs Hard Lock）** | `softLock = 2026-10-31`, `hardLock = 2026-10-31`：`Standard` 无 Lock 权限；设置 Hard Lock `2026-10-31` 后，即使 `Administrator` 提交 `2026-10-15` 平衡凭证也返回 `400/422 PERIOD_HARD_LOCKED` (`E37-PAGE`) |
| **EDGE-07** | **跨财年动态结转 & 银行透支重分类** | 在 `2026-06-15` 过账 `Sales 500`、在 `2026-07-10` 使 `Bank` 净透支 `-100` -> 查询 `Balance Sheet (2026-08-31)` 时，`Retained Earnings` 自动包含 `+500`，`Current Year Earnings` 仅含 7 月后损益，透支银行出现在 `Current Liabilities` |
| **EDGE-08** | **Cash Basis BAS & P&L 跨引擎一致性** | 在 `mvp-and-extended-fixtures.json` `suite_2` 累积数据上切换 Cash 制：未付 `BILL-0001 (110)` 同时退出 P&L (`Net Profit` `50 -> 150`) 与 BAS (`1B: 10->0, Payment 9: 15->25`)；`showOnCashBasisReports=true` 手工凭证 `#5` 同时留存两端（`E35`, `E36`） |
| **EDGE-09** | **BAS 定稿后补录迟到凭证（Unfiled Amounts）** | Q1 (`Jul-Sep`) BAS 已 `Finalise` (`maxJournalNumber = 10`)；Adviser 补记一张 `2026-09-20` 销售发票 `110.00` (`journalNumber = 11`) -> 查询 Q2 (`Oct-Dec`) BAS 时自动捕获该 `Unfiled` 销项税 `+10` |
| **EDGE-10** | **同日同金额银行 CSV 导入 + 并发 Match 锁** | 导入含两条完全相同 `14/11/2026, +110.00` 的 CSV 均成功入库（`2` 条 `UNRECONCILED`），二次重复上传同 CSV 去重为 `0` 新增；并发对同一流水 `Match` 仅 1 个成功，另 1 个 `409 Conflict` |

---

## 3. 扩展回归测试矩阵（`suite_2_extended_regression`, 对应 `E29–E38`）

详见机器可读真值夹具 [mvp-and-extended-fixtures.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/tests/mvp-and-extended-fixtures.json) 中的 `suite_2_extended_regression`：
- **EXT-01（Auto-Reverse 手工凭证）：** `2026-11-14` 过账 `#5`（Dr `469 100.00` / Cr `850 100.00`, `autoReversingDate=2026-12-01`）同步生成 `#4`（`Reversal: ...`）。
- **EXT-02（Purchase Bill 含税录入归一化）：** `BILL-0001` 以 `INCLUSIVE 110.00` 录入，批准后单价归一展示 `100.00 + 10.00 GST = 110.00`（`AWAITING_PAYMENT`）。
- **EXT-03（部分收款 + 贷项单核销）：** `INV-0002 (110.00 EX)` -> 收款 `PART-PAY-55 (55.00)` -> `CN-0003 (55.00 EX)` 批准自动核销 `INV-0002`，两者皆置 `PAID`，GL `1071` 累积 48 行借贷平衡 `815.00 / 815.00`。
- **EXT-04 / EXT-05（Accrual vs Cash P&L 与 BAS 对照）：** Accrual `Net Profit 50.00 / BAS Payment 15` vs Cash `Net Profit 150.00 / BAS Payment 25`。
- **EXT-06（Hard Lock & 不平凭证负向拦截）：** 锁账日 `2026-10-31` 拦截 `2026-10-15` 凭证（`HTTP 400`），不平 `50.00 vs 50.01` 拦截。
