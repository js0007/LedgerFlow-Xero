# 06_MVP实施路线图（AI Coding Execution Roadmap）

> **面向读者：** Codex 等 AI Coding Agent 及工程负责人。  
> **实施原则：** 严格遵守“**先夯实不可变双分录总账与税务内核（M0–M1），再接通 P1 业务单据与银行对账过账（M2），再打通四大报表与 BAS 水位线引擎（M3），最终以自动化端到端测试跑通三笔 MVP 验收场景收口（M4）**”。

---

## Milestone 0：工程底座、DB Schema 与多租户基础设施（预计 2 天）

- **交付物：**
  - 初始化 Monorepo（`apps/api`, `apps/web`, `packages/shared-decimal-tax`）与 Docker PostgreSQL 16。
  - 执行 [accounting_core.sql](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/schemas/accounting_core.sql) DDL，含 Append-Only Trigger 与 RLS/租户表。
  - 实现 AU Org 建账种子服务（`OrgSeedService`）：一键创建新组织时自动初始化 **54 个 AU 标准科目**（精确匹配 [E04-au-default-coa.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/dom/E04-au-default-coa.json)）、**6 个 Active AU TaxRates**（含 `canApplyTo*` 与 `bas_field_names`）与默认 `org_settings`（`AUD`, `30 Jun`, `Accrual`, `Simpler BAS`, `G1 = INCLUSIVE`）。
  - 实现 JWT 鉴权、角色校验（`ADVISER`/`STANDARD`/`READONLY`）、`Idempotency-Key` 中间件与 Correlation ID 日志。
- **验收标准（DoD）：** 单元测试验证新组织创建后立即可查出 54 科目与 6 个税率；直接 SQL 执行 `UPDATE journal_lines` 被触发器拦截。

---

## Milestone 1：不可变总账内核、Tax/Rounding 引擎、Lock Dates 与 Manual Journals（预计 3 天）

- **交付物：**
  - `DecimalTaxEngine`（纯函数包）：实现 `EXCLUSIVE / INCLUSIVE / NO_TAX` 逐行 2 位小数舍入计算与科目大类税码校验。
  - `JournalPostingService`：实现借贷平账、单调 `journal_number` 颁发、两层 Lock Dates 检查（Soft/Hard）、以及逆向冲销 `reverseJournal()`。
  - `ManualJournals` API + SPA 页面：受控科目过滤（禁止选 `610`, `800`, `820`? 注：`820 GST` 由税务引擎自动过账或顾问锁控，严格过滤 `AR/AP/Bank/Retained Earnings` 等系统控制科目）、Draft/Post/Void 状态流转、`Auto-reversing date`、Cash basis 标识、剪贴板批量粘贴行 UI。
  - `COA` & `TaxRates` & `Financial Settings`（含 Lock Dates 修改记录进 `audit_logs`）前后端页面。
- **验收标准（DoD）：** 不平分录被 HTTP 422 拦截；Standard 用户在 Soft Lock 前不可记账，Adviser 可记账；Hard Lock 前所有角色不可记账；Manual Journal 自动拒绝选 `610 AR` / `800 AP` / `Bank`。

---

## Milestone 2：AR / AP / Payments 与 Bank Reconciliation / Cash Coding 闭环（预计 4 天）

- **交付物：**
  - `Contacts` 模块 CRUD 与客户/供应商视图派生。
  - `Invoices & Bills & Credit Notes` API 与轻量化编辑 UI（Tax Incl/Excl 切换、`DRAFT -> AUTHORISED -> PAID / VOIDED`、Approve 即原子生成 `ACCREC`/`ACCPAY` 凭证）。
  - `Payments` 独立核销服务（只过账 `Bank <-> AR/AP`，更新 `amount_paid` 与发票状态 `PAID`）。
  - `Banking & Reconciliation` 模块：银行账户创建、CSV 流水导入（去重 `import_hash`）、Twin Balances 实时计算、简化 Match 建议引擎（按未付发票余额+参考号匹配）+ **一键 `OK` 原子核销** + `Create Receive/Spend Money` + `Transfer` + `Cash Coding` 网格页。
- **验收标准（DoD）：** 支持多标签页并发 Match 防重保护（`409 Conflict`）；支持部分收款核销；未对账 CSV 导入后首页立即展示 Statement vs Book 差异。

---

## Milestone 3：实时报表引擎（TB / P&L / BS / Journal / Subledger）与 AU Simpler BAS 工作台（预计 3 天）

- **交付物：**
  - Reporting Engine（统一参数 `from`, `to`, `basis=ACCRUAL|CASH`）：
    - `Journal Report`（按 `journal_number` 倒序/正序展示并标注 Reversal 来源）
    - `Account Transactions` 下钻（关联源单据号与 Contact）
    - `Trial Balance`（动态切分本财年与历史损益）
    - `Profit & Loss`（支持 Accrual 与 Cash 双口径）
    - `Balance Sheet`（**动态 `Current Year Earnings -> Retained Earnings` 跨年结转 + `Bank < 0` 动态重分类至流动负债**）
  - AU Simpler BAS 引擎与 `/tax/bas` 页面：
    - `Accruals` 与 `Cash`（按 Payment 实付比率拆分原单行税额）双口径计算；
    - 支持账套配置 `bas_g1_mode` (`INCLUSIVE` 默认 `220` / `EXCLUSIVE` 可切 `200`)；
    - `min_journal_number` / `max_journal_number` 水位线、`Unfiled amounts` 迟到增量捕获、`Save Draft / Finalise`。
- **验收标准（DoD）：** 执行跨 6 月 30 日财年末测试数据时，BS 资产总计 == 负债+权益，无需任何物理年结分录；透支银行在 BS 自动列示在流动负债下。

---

## Milestone 4：端到端 MVP 三笔业务自动化验收与全局一致性审计（预计 2 天）

- **交付物：**
  - 在 CI 中运行完整自动化测试套件 [mvp-acceptance-scenarios.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/tests/mvp-acceptance-scenarios.md)（包含 3 笔核心业务全链路 API/UI 测试 + 边界用例测试）。
  - 运行 `verifyOrgIntegrity(orgId)` 全场一致性校验器通过 0 告警。
  - P2 占位导航页（Payroll / Fixed Assets / Inventory）上线并附明确引导。
- **总退出门槛（Exit Gate）：** 3 笔 MVP 业务端到端测试 100% 绿灯，全部 7 项会计不变量校验通过，零 Float 货币运算。

---

## 实际工程交付与验证状态（Python 3.11 + Flask + SQLite + React 18 高保真复刻）

本路线图已按审查纠正后的技术选型在 `app/` 目录完成完整独立运行实现（而非仅纸面设计）：

1. **后端工程 ([app/backend/](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/app/backend/app.py))：**
   - **存储与并发底座：** SQLite 3 (`PRAGMA foreign_keys = ON`, `WAL` 模式) + [accounting_core_sqlite.sql](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Accounting-SaaS-Blueprint/schemas/accounting_core_sqlite.sql)，通过数据库触发器 (`trg_journals_immutable_*`, `trg_journal_lines_immutable_*`, `trg_audit_logs_immutable_*`) 物理封死总账与审计日志篡改；货币全部采用整数分 (`*_cents`) 与 `Decimal` (`ROUND_HALF_UP`)。
   - **完整域服务：** 54 AU 科目 + 6 Active / 11 AU TaxRates 建账种子、`!VD61z` 演示账套与安全 FK 顺序一键重置、Quotes -> Invoices / POs -> Bills 转换与状态流转、Credit Notes 共享流水号与多张单据核销、双栏银行对账（`MATCH_EXISTING_PAYMENT` / `MATCH_INVOICE` 含 Minor Adjustment / `CREATE_BANK_TX` / `TRANSFER` / `Unreconcile` / `Remove & Redo`）、Bank Rules 条件评分、Cash Coding 批处理、47 科目过滤与 Auto-Reverse Manual Journals、Adviser Find & Recode、Conversion Balances（`840` 自动轧平）、Assurance Dashboard、六大数据报表（P&L 双口径 / Balance Sheet 透支重分类与虚拟年结 / Trial Balance / Journal Report / Account Transactions / Aged AR & AP 6 账龄段）与 AU Simpler BAS（G1/G10/G11/1A/1B/9 水位线与 Unfiled 捕获）。
2. **高保真前端 ([app/frontend/](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/app/frontend/package.json))：**
   - **React 18 + TypeScript + Vite 6** 编译打包至 `app/frontend/dist/` 由 Flask 同源托管。完整还原 Xero 蓝色顶部导航、双组织切换 (`!VD61z` & `!W5gW!`)、三角色权限切换 (`ADVISER` / `STANDARD` / `READONLY`)、分栏银行对账 `OK` 按钮、发票内联税态编辑器及全套报表工作台。
3. **启动方式：**
   ```powershell
   cd d:\ai-work\au-faiw\xero调研\app
   $env:PYTHONPATH = "d:\ai-work\au-faiw\xero调研\app"
   .\.venv\Scripts\python.exe -m backend.app
   # 访问 http://127.0.0.1:5000
   ```
