# UI Design Tokens & 核心页面线框规格（Prototypes）

> **设计来源：** 参考 Xero XUI (`E01` `#1f68dd` 顶部 64px 蓝栏、`#f2f3f4` 画布、`Inter` 等宽数值排版、`E07` 粘性底部操作栏、`E12` 双栏对账框、`E28` BAS 汇总表) 提炼独立产品统一组件规格。

---

## 1. Design Tokens（CSS Custom Properties）

```css
:root {
  /* Brand & Shell */
  --color-nav-bg: #1d4ed8;
  --color-nav-hover: #1e40af;
  --color-brand-primary: #0078c8;
  --color-success-match: #15803d;
  --color-success-bg: #dcfce7;
  --color-warning-bg: #fef3c7;
  --color-danger: #dc2626;

  /* Surface & Text */
  --color-canvas: #f2f3f4;
  --color-card-bg: #ffffff;
  --color-border-subtle: #e2e8f0;
  --color-text-primary: #000a1e;
  --color-text-muted: #475569;

  /* Typography */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-size-h1: 1.5rem;     /* 24px, weight 700 */
  --font-size-body: 0.9375rem;/* 15px */
  --font-size-table: 0.875rem;/* 14px */

  /* Layout */
  --nav-height: 64px;
  --sticky-footer-height: 60px;
  --radius-card: 6px;
}

.numeric-cell {
  font-variant-numeric: tabular-nums;
  text-align: right;
  font-feature-settings: "tnum";
}
```

---

## 2. 关键工作台线框图（Key Screen Wireframes）

### 2.1 双栏银行对账工作台 (`/banking/:id/reconcile`, 对标 `E12`, `E22`, `E23`)

```text
+---------------------------------------------------------------------------------------------------+
| [Logo] Org: Acme Demo v | Home | Sales | Purchases | Banking* | Reporting | Accounting | Tax | +  |
+---------------------------------------------------------------------------------------------------+
| Bank Reconciliation: Business Operating Account (0123456789)              [Import CSV] [Cash Coding] |
| Statement Balance: $220.00   |   Balance in System: $110.00   |   Unreconciled: 1 line ($110.00)  |
+----------------------------------------------------+---+------------------------------------------+
| 银行对账单流水（Bank Statement Lines）             |   | 记账 / 核销工作区（Match | Create | Xfer）|
+----------------------------------------------------+---+------------------------------------------+
| [Card #1] 14 Nov 2026                              |   | [Tab: Match*] [Create] [Transfer]        |
| Payee: Acme Customer Pty Ltd                       |OK | GREEN MATCH FOUND: INV-0001 ($110.00)    |
| Desc:  Invoice Payment INV-0001                    |   | Due: 21 Nov 2026 | Diff: $0.00           |
| Received: +$110.00 AUD                             |   | [Details]                                |
+----------------------------------------------------+---+------------------------------------------+
| [Card #2] 14 Nov 2026                              |   | [Tab: Match] [Create*] [Transfer]        |
| Payee: Walk-in Cash Customer                       |OK | Who:   [ Walk-in Cash Customer        ]  |
| Desc:  Cash Coding Direct Sale                     |   | What:  [ 200 - Sales                  ]  |
| Received: +$110.00 AUD                             |   | Tax:   [ GST on Income (10% Incl.) v  ]  |
|                                                    |   | Why:   [ Cash Coding Direct Sale      ]  |
+----------------------------------------------------+---+------------------------------------------+
```

### 2.2 Manual Journal 编辑器与底部粘性栏 (`/accounting/journals/new`, 对标 `E07`)

```text
+---------------------------------------------------------------------------------------------------+
| Narration*: [ Accrual Adjustment Nov 2026      ]  Date: [ 30 Nov 2026 ]  Auto-reverse: [ Optional ]|
| Amounts are: [ No tax v ]                         [x] Show journal on cash basis reports          |
+---------------------------------------------------------------------------------------------------+
| # | Description        | Account (Filtered: Non-System Only) | Tax Rate      | Debit   | Credit |
| 1 | Prepaid rent exp   | 429 - Rent                          | BAS Excluded  |  500.00 |        |
| 2 | Prepayment release | 620 - Prepayments                   | BAS Excluded  |         | 500.00 |
| [+ Add line] [Paste lines]                                     | Total         |  500.00 | 500.00 |
+---------------------------------------------------------------------------------------------------+
| [Sticky Footer] [ Cancel ]                                     [ Save as draft ]  [ Post Journal ]|
+---------------------------------------------------------------------------------------------------+
```

### 2.3 AU Simpler BAS 汇总页 (`/tax/bas`, 对标 `E20`, `E28`)

```text
+---------------------------------------------------------------------------------------------------+
| Activity Statement: Oct - Dec 2026                 Method: Accruals | Period: Quarterly | [Draft] |
| Tabs: [ Summary* ] [ Transactions (2) ]                                   Amount Payable: $20 AUD |
+---------------------------------------------------------------------------------------------------+
| Goods and services tax (GST)                       | Code | Label                    | Amount     |
| Reporting Basis: [G1 GST Inclusive v]              | G1   | Total sales (Incl. GST)  |      $220  |
+----------------------------------------------------+------+--------------------------+------------+
| Amounts you owe the ATO                            | 1A   | GST on sales             |       $20  |
|                                                    | 8A   | Total owed to the ATO    |       $20  |
+----------------------------------------------------+------+--------------------------+------------+
| Amounts the ATO owes you                           | 1B   | GST on purchases         |        $0  |
|                                                    | 8B   | Total owed by the ATO    |        $0  |
+----------------------------------------------------+------+--------------------------+------------+
| Payment                                            | 9    | Your payment amount      |       $20  |
+----------------------------------------------------+------+--------------------------+------------+
| [Sticky Footer] [ Export CSV/PDF ]                           [ Save Draft ] [ Finalise Statement ]|
+---------------------------------------------------------------------------------------------------+
```
