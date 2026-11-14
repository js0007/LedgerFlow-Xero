# E24–E28 干净试用账套 MVP 三笔核心业务实测轨迹（AU, AUD, 10% GST）

> **测试组织：** `Southern Cross Office Supplies Pty Ltd` (`!W5gW!`) — AU 新建试用账套（初始 0 交易，财年末 `30 June`，Accruals Basis）  
> **银行账户：** `Business Operating Account` (`AUD`, BSB/Acc `0123456789`)  
> **执行时间：** 2026-11-14  
> **关联证据：** `E21-PAGE`, `E22-CSV`, `E22-PAGE`, `E23-PAGE`, `E24-PAGE`, `E25-PAGE`, `E26-PAGE`, `E27-PAGE`, `E28-PAGE`, `E28b-PAGE`, `E28-NET`

---

## 1. 测试执行步骤与系统分录实测 (`[Observed]`)

### 场景 1：创建并批准 110 AUD 含税销售发票
- **操作：** 新建发票 `INV-0001`，客户 `Acme Customer Pty Ltd`，日期 `14 Nov 2026`，Amounts are `Tax inclusive`，明细 `Consulting Service - MVP Scenario 1`，Qty `1`，Unit price `110.00`，Account `200 - Sales`，Tax rate `GST on Income` (`10%`)，点击 `Approve`。
- **BFF 实测 (`POST /api/invoicing/invoice/create?intent=CreateOrUpdate`, `E21-PAGE`)：**
  - 请求体 `TaxType: "INCLUSIVE"`，返回 `Totals: { SubTotal: 100.00, Tax: 10.00, Amount: 110.00 }`。
- **总账过账分录（Journal ID `1`, `E24-PAGE`）：**

| Account Code | Account Name | Debit (AUD) | Credit (AUD) | Tax Type |
|---|---|---:|---:|---|
| 610 | Accounts Receivable | 110.00 | - | - |
| 200 | Sales | - | 100.00 | OUTPUT |
| 820 | GST | - | 10.00 | - |

### 场景 2：导入银行流水并完成客户收款 110 AUD 对账核销
- **操作：** 导入银行对账单 [E22-mvp-bank-statement.csv](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E22-mvp-bank-statement.csv)（含 2 笔 `+110.00` AUD 入账流水），对账前 `Statement Balance = 220.00`, `Balance in Xero = 0.00` (`E22-PAGE`)。
- **Match 实测：** `POST https://api.bank-reconciliation.xero.com/v2/suggestions` 在 `matches[]` 中自动匹配 `INV-0001`；点击 `OK` 后触发 `POST /ajaxpro/BankRec_BankRec.ashx` (`SUBSTYPE/ACCREC`)，同步创建 `Payment` 并标记银行行已对账，`Balance in Xero` 升至 `110.00`。
- **总账过账分录（Journal ID `2`, `E24-PAGE`）：**

| Account Code | Account Name | Debit (AUD) | Credit (AUD) | 说明 |
|---|---|---:|---:|---|
| - | Business Operating Account | 110.00 | - | 银行收款入账 |
| 610 | Accounts Receivable | - | 110.00 | 核销 `INV-0001`，无重复确认收入与 GST |

### 场景 3：银行收款 110 AUD 直接编码入账（Create Receive Money / Cash Coding 等价总账路径）
- **操作：** 在试用账套中 `FastCoding.aspx` 返回 404（版本/权限门控，Demo 环境已于 `E13-PAGE` 验证）；通过银行对账单行右侧 `Create` 面板录入 `Who: Walk-in Cash Customer`, `What: 200 - Sales`（自动带出 `GST on Income` 10% 含税）, `Why: Cash Coding Direct Sale`，点击 `OK` (`E23-PAGE`)。
- **界面回执：** `Statement Balance: 220.00 Reconciled`（`Great job! You've reconciled all the transactions for this account`）。
- **总账过账分录（Journal ID `3`, `E24-PAGE`）：**

| Account Code | Account Name | Debit (AUD) | Credit (AUD) | Tax Type |
|---|---|---:|---:|---|
| - | Business Operating Account | 110.00 | - | - |
| 200 | Sales | - | 100.00 | OUTPUT |
| 820 | GST | - | 10.00 | - |

---

## 2. 期末总账、四大财务报表与 BAS 最终输出核对 (`[Observed]`)

| 核对维度 | 报表路径 / 接口 | Xero 实测结果 (`!W5gW!`) | 与 MVP 验收预期对比 | 证据 |
|---|---|---|---|---|
| **Journal Report (1098)** | `reporting.xero.com/!W5gW!/v1/Run/1098` | 共 3 笔总账分录（ID 1–3），累计 Debit `330.00` = Credit `330.00` | 完全一致 | `E24-PAGE` |
| **Trial Balance (1005)** | `As at 30 Nov 2026` | `Business Operating Account` Dr `220.00`；`200 Sales` Cr `200.00`；`820 GST` Cr `20.00`；`610 AR` 净额 `0` 隐藏 | 完全一致 | `E25-PAGE` |
| **Profit & Loss (1016)** | `Nov 2026` (Accrual) | `Trading Income -> Sales = 200.00`；`Gross Profit = 200.00`；`Net Profit = 200.00` | 完全一致 | `E26-PAGE` |
| **Balance Sheet (1017)** | `As at 30 Nov 2026` | `Bank = 220.00` (`Total Assets = 220.00`)；`Current Liabilities -> GST = 20.00`；`Net Assets = 200.00`；`Equity -> Current Year Earnings = 200.00` | 完全一致 | `E27-PAGE` |
| **Simpler BAS (Oct–Dec 2026)** | `/api/bas/statement` & `/api/bas/gstReport/v2` | `G1 Total sales = 220` (**GST inclusive** 口径，Net 200 + GST 20)；`1A = 20`；`1B = 0`；`8A = 20`；`9 Payment = 20` | `1A/1B/9` 完全一致；**关键差异发现**：Xero AU Simpler BAS `G1` 默认展示含税总额 `220`（`totalGross`），而非不含税 `200`（`totalNet`） | `E28-PAGE`, `E28b-PAGE`, `E28-NET` |
