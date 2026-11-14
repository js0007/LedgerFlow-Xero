# Xero Research 产品研究资产库

本目录沉淀对 **Xero**（澳大利亚区 Web 产品、官方帮助中心、公开 Accounting API 及 ATO 税务规则）的系统化、可追溯研究事实与原始证据。

> [!IMPORTANT]
> 本目录仅记录**客观研究事实与明确标注来源的推断**；所有独立产品的设计方案与开发规格统一存放在 [Accounting-SaaS-Blueprint](../Accounting-SaaS-Blueprint/README.md) 中，两者通过证据 ID 保持双向追溯，严格分离。

---

## 1. 证据分类与标注规范

所有关键结论均附带以下五类标签之一及对应证据 ID：

| 标签 | 含义 | 使用规则 |
|---|---|---|
| **Observed** | 通过 Chrome DevTools MCP 在 Xero Web 真实页面/DOM/Network 中直接观察到的行为 | 引用 `E*` 证据编号与采集时间 |
| **Documented** | Xero 官方文档（`central.xero.com` / `developer.xero.com`）或 ATO（`ato.gov.au`）明确说明的规则 | 引用 `official-sources-digest.md` |
| **Inferred** | 基于 Observed 与 Documented 事实结合会计/软件工程知识做出的合理推断 | 明确说明推理依据 |
| **Proposed** | 面向独立会计 SaaS 提出的自主设计建议（详述于 Blueprint） | 用于衔接 Blueprint 设计决策 |
| **Unknown** | 当前会话尚未验证或受版本权限限制无法直接实操的事项 | 注明原因与替代路径 |

---

## 2. 研究报告目录

- [00_研究计划与进度.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/00_%E7%A0%94%E7%A9%B6%E8%AE%A1%E5%88%92%E4%B8%8E%E8%BF%9B%E5%BA%A6.md)：研究进度矩阵、P0/P1/P2 范围验收与全阶段跟踪
- [01_产品全景与交互设计.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/01_%E4%BA%A7%E5%93%81%E5%85%A8%E6%99%AF%E4%B8%8E%E4%BA%A4%E4%BA%92%E8%AE%BE%E8%AE%A1.md)：产品信息架构、全局导航、MFE 技术壳、Homepage、Settings、XUI 视觉样式
- [02_核心业务流程与会计规则.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/02_%E6%A0%B8%E5%BF%83%E4%B8%9A%E5%8A%A1%E6%B5%81%E7%A8%8B%E4%B8%8E%E4%BC%9A%E8%AE%A1%E8%A7%84%E5%88%99.md)：账套与双层锁账、54 科目与系统锁、不可变分录与冲销、AU GST/BAS 口径、AR/AP/银行对账与 MVP 三笔实测验证
- [03_数据对象与接口研究.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/03_%E6%95%B0%E6%8D%AE%E5%AF%B9%E8%B1%A1%E4%B8%8E%E6%8E%A5%E5%8F%A3%E7%A0%94%E7%A9%B6.md)：12+ 核心业务对象三重视角映射（UI 表单 × BFF JSON × Public API）、租户隔离头与限流契约
- [04_技术架构与实现原理研究.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/04_%E6%8A%80%E6%9C%AF%E6%9E%B6%E6%9E%84%E4%B8%8E%E5%AE%9E%E7%8E%B0%E5%8E%9F%E7%90%86%E7%A0%94%E7%A9%B6.md)：MFE Shell + BFF + Legacy 演进机制、Virtual Year-End Close、BAS 水位线、架构启示与反模式清单
- [official-sources-digest.md](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A9%B6/Xero-Research/evidence/official-docs/official-sources-digest.md)：ATO / Xero Central / Xero Developer 官方规则摘要

---

## 3. 原始证据索引（Evidence Registry）

> 安全原则：所有证据均已脱敏，不包含密码、Cookie、Bearer JWT、真实个人邮箱或敏感凭据。

| 证据 ID | 采集时间 | 业务模块 | 证据文件 / 位置 | 核心记录内容 |
|---|---|---|---|---|
| **E01–E10** | 2026-11-14 21:08–21:11 | 全局壳、设置、COA、税率、Manual Journals、报表中心 (`!W5gW!` 初始态) | [pages/](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/), [E01-navigation-map.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/dom/E01-navigation-map.json), [E04-au-default-coa.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/dom/E04-au-default-coa.json), [E06-manual-journals-bff-sanitized.json](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/network/E06-manual-journals-bff-sanitized.json) | 80 项导航、AU 54 默认科目、11 条税率含 `canApplyTo*` 约束、Manual Journals BFF、Financial Settings |
| **E11–E15** | 2026-11-14 | Demo Company (`!VD61z`) 首页、银行对账、Cash Coding、发票 | [E11](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E11-demo-homepage.webp), [E12](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E12-demo-bank-rec.webp), [E13](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E13-demo-cash-coding.webp), [E14](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E14-demo-invoices-list.webp), [E15](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E15-demo-invoice-paid.webp) | 样本企业仪表盘、Match/Create/Transfer/Discuss 双栏对账、`FastCoding.aspx` Cash Coding、已付款发票核销链 |
| **E16–E18** | 2026-11-14 | Demo 总账、试算平衡与动态跨年资产负债表 | [E16](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E16-demo-journal-report.webp), [E17](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E17-demo-trial-balance.webp), [E18 (Jun)](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E18-demo-balance-sheet.webp), [E18 (Nov)](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E18-demo-balance-sheet-nov2026.webp) | `ID 736 Reversal of ID 729`、RX 报表引擎、`CYE -> Retained Earnings` 动态跨年结转、透支银行自动重分类 |
| **E19–E20** | 2026-11-14 | Demo BAS Settings / Summary / API | [E19](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E19-demo-bas-settings.webp), [E20](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E20-demo-bas-summary.webp), [E20-NET](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/network/E20-demo-bas-gstreport-sanitized.json) | `G1=41,039`, `1A=3,730`, `1B=2,320`, `Payment=1,410`、多税种 `basFieldNames` 映射样本 |
| **E21–E23** | 2026-11-14 | 干净账套 `!W5gW!` MVP 3 笔业务录入与银行对账 | [E21](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E21-mvp-scenario1-invoice.webp), [E22-CSV](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E22-mvp-bank-statement.csv), [E22](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E22-mvp-bankrec-before.webp), [E23](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E23-mvp-bankrec-create-cashsale.webp) | `INV-0001` (`110 AUD` 含税) 批准、CSV 2 笔流水导入、`v2/suggestions` Match 核销、`Create Receive Money` 完结对账 |
| **E24–E28b** | 2026-11-14 | 干净账套 `!W5gW!` MVP 期末总账、报表与 BAS 验收 | [E24 轨迹](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E24-mvp-3scenarios-trace.md), [E24](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E24-mvp-journal-report.webp), [E25](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E25-mvp-trial-balance.webp), [E26](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E26-mvp-pnl.webp), [E27](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E27-mvp-balance-sheet.webp), [E28](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E28-mvp-bas.webp), [E28b](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E28b-mvp-bas-transactions.webp), [E28-NET](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/network/E28-mvp-bas-sanitized.json) | Journal ID `1–3`（`330/330`）、TB（Sales `200`, Bank `220`, GST `20`, AR `0`）、P&L (`200`)、BS (`220/20/200`)、BAS (`G1=220` 含税, `1A=20`, `1B=0`, `9=20`) |
| **E29–E38** | 2026-11-14–15 | 查漏补缺：MJ 47/54 与 Auto-Reverse、Bill、部分收款、CN 核销、Cash BAS/P&L、Lock Dates、P2 边界 | [E29-E38 轨迹](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/interactions/E29-E38-extended-exploration-trace.md), [E29-NET](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/network/E29-mj-accounts-diff-sanitized.json), [E29](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E29-mj-autoreverse-posted.webp), [E30](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E30-conversion-balances.webp), [E31](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E31-user-roles-rbac.webp), [E32](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E32-bill-approved.webp), [E33](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E33-credit-note-allocated.webp), [E34](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E34-bank-tx-actions.webp), [E35](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E35-gl-and-cash-pnl.webp), [E36](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E36-cash-bas.webp), [E36-NET](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/network/E36-cash-vs-accrual-bas-sanitized.json), [E37](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E37-lock-date-blocked.webp), [E38](file:///d:/ai-work/au-faiw/xero%E8%B0%83%E7%A0%94/Xero-Research/evidence/pages/E38-p2-boundaries.webp) | 47/54 排除7科、`#5/#4` Auto-Reverse、`BILL-0001`、部分收款 + `CN-0003`、`GL 1071` (`815/815`)、Cash P&L (`150`) & Cash BAS (`9=25`) vs Accrual (`50`, `9=15`)、Hard Lock `HTTP 400`、P2 边界 |
