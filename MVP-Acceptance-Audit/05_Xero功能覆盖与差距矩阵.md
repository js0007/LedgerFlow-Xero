# 05 Xero 功能覆盖与差距矩阵

> **对比基准：** `Xero-Research/01_Xero全站产品功能地图.md`（13 个产品大域）与 `Accounting-SaaS-Blueprint/06_MVP实施路线图.md`。  
> **口径说明：** 本矩阵明确区分“当前 Stage 1 核心范围缺口”与“已合规暂缓的外围生态/直连功能（不计入当前研发缺陷）”。

---

## 一、13 大产品域总覆盖矩阵

| Xero 产品域 | 核心子功能 | 当前状态分级 | 关键差距说明与证据 |
|---|---|---|---|
| **A. Dashboard & Global Nav** | 组织切换 / Demo 沙盒 / 快捷新建 / Twin Balances / AR & AP 概览 / Account Watchlist | **已实现（部分缺陷）** | 缺现金流入出柱状图；Dashboard AR 未扣减 Credit Note (`$9,621.50` vs `$9,561.00`)；无 URL 路由 **[已验证]** |
| **B1. Sales — Invoices** | 列表/新建/Draft 编辑/行级算税/批准/Void/部分收款/付款删除 | **已实现且核心通过** | 缺 **Draft 物理删除、Authorised 改单、Repeating Invoices、发邮件/PDF 导出、在线收款链接** **[已验证 / 代码推断]** |
| **B2. Sales — Credit Notes** | 新建/批准/分配核销至 Invoice | **已实现（关键分支缺失）** | 缺 **Credit Note 现金退款（`POST /payments` 404）**、**解除核销（Deallocate）** **[已验证]** |
| **B3. Sales — Quotes** | 创建、转为 Invoice（幂等） | **已实现但尚未充分验证** | 缺 **Draft 编辑、删除、Mark Sent / Declined / Accepted 状态流转**；转单按钮缺报错处理 **[已验证 / 代码推断]** |
| **C1. Purchases — Bills & CN** | Bills 列表/批准/Void/付款/Supplier Credit Note 分配 | **已实现且核心通过** | 同 Sales：缺 **Repeating Bills、Draft 删除、Authorised 改单、Supplier CN 现金退款、ABA 批量付款文件导出** **[代码推断]** |
| **C2. Purchases — Purchase Orders** | PO 创建、Copy to Bill | **已实现但尚未充分验证** | 缺 **PO 编辑、删除、状态切换、部分收货转单** **[代码推断]** |
| **D. Contacts & Products** | Customers/Suppliers 主数据、默认科目与税率、无追踪 SKU 目录 | **Contacts 已实现；Products 部分实现** | Contacts 缺往来单据对账明细页与分组合并；Products 缺前端编辑/删除/归档；**Tracked Inventory 暂不需要实现** **[已验证]** |
| **E1. Banking — Twin Balances & CSV** | 多银行账户、Statement vs Book 双余额、CSV 导表去重 | **已实现（导入历史去重边界缺陷）** | 同日跨批次导入同金额/描述真实第二笔消费存在 `occ_idx=1` 碰撞风险 **[代码推断]**；**Bank Feeds 直连暂不需要实现** |
| **E2. Banking — Reconciliation** | Suggest Match / Match 多选与微调 / Create / Transfer / Discuss / Unreconcile / Remove & Redo | **已实现（存在严重账务漏洞）** | **Transfer 双边重复入账**、**Remove & Redo 漏冲微调分录**、**Bank `RECEIVE+INPUT` 税号反向** **[已验证]** |
| **E3. Banking — Cash Coding & Rules** | 批量网格分类与批过账；ALL/ANY Bank Rules（定额+比例拆分） | **已实现（事务原子性与前端编辑缺失）** | **Cash Coding 批过账非原子+绕过 version**；**Bank Rules 缺前端 Edit 入口** **[已验证]** |
| **F1. Accounting — COA & Manual Journals** | 54 AU 科目、47 手工分录可选过滤、Draft/Posted/Void、Auto-Reversing | **已实现（契约及含税 MJ 反向漏洞）** | COA 前端 `OVERHEADS`/清税/归档错位；**含税 MJ 借 OUTPUT/贷 INPUT 税号恒正**；前端隐藏 Posted MJ 编辑 **[已验证]** |
| **F2. Accounting — Controls & Tools** | 两层 Lock Dates、Tracking Categories (2 组)、Conversion Balances、Find & Recode、Assurance、Audit Log | **已实现（Find & Recode 与期初口径漏洞）** | **Find & Recode 未付发票泄漏入 Cash P&L 且不支持改 Tax Rate**；Conversion Balances 缺与期初 AR/AP 明细联动校验；Tracking 缺重命名/停用 **[已验证 / 代码推断]** |
| **G1. Reporting — 核心财务报表** | P&L (Accrual/Cash/Tracking)、BS (Cross-FY/透支重分类)、TB、Journal Report、Acct Tx、Aged AR/AP、Short-term Cash Flow | **已实现且勾稽主干准确** | BS/TB/Aged 缺 CSV 导出；Cash Flow 无趋势图与自定义预测调节项；缺多期间横向对比与自定义报表布局版式 **[已验证]** |
| **G2. Reporting — AU Simpler BAS** | G1 / 1A / 1B / 9（Accrual & Cash）、Whole Dollar、Finalise 水印与 Unfiled | **已实现（存在税码拼写与回溯 CN 漏洞）** | `bas.py` `"EXEMPTINPUT"` 拼写错导致 `EXEMPTEXPENSES/EXEMPTCAPITAL` 漏出内部 G10/G11；**回溯 Cash CN 核销未进 Unfiled** **[已验证]**；**ATO SBR/PLS 申报直连暂不需要实现** |
| **H. Tracked Inventory** | 移动加权平均 COGS、盘点调账 (`New adjustment`) | **暂不需要实现**（仅无追踪目录已做） | 明确列为 P2/Stage 2 后评估域 |
| **I. Fixed Assets** | 资产卡片台账、折旧运行 (`Run depreciation`)、处置损益 | **仅有占位（联动活科目）** | UI 诚实展示 Stage 2 规划及 `710-721 / 416` 活余额 **[已验证]** |
| **J. Projects** | 项目立项、工时、成本预算与盈亏 | **仅有占位（指引 Tracking 替代）** | UI 指引当前用 Tracking Categories 替代，符合阶段范围 **[已验证]** |
| **K. Expenses** | 员工小票拍照报销、审批支付 (`801` 科目) | **仅有占位** | 建议在 Stage 2 作为重点补齐项 |
| **L. AU Payroll & STP** | Pay Runs、Super、PAYG Withholding、STP2 | **仅有占位（暂不需要实现）** | 法规合规极重，持续延后 **[已验证]** |
| **M. App Store & Settings** | 组织/财税设定、双层锁账、税率表、Connected Apps 页面 | **Settings 已实现；App Store 为静态目录/表骨架** | 缺税率新增与编辑、成员权限管理页面；App Store 开放 OAuth 生态暂不需要实现 **[已验证]** |

---

## 二、Stage 2 功能归类决策建议

1. **必须作为 Stage 1 扫尾闭环（P0/P1 修复后即达到“可用 MVP+”）：**
   - 商业单据完整态：Credit Note 现金退款 + 解除核销、Draft 删除、Authorised 编辑、Quote/PO 状态修改与列表同步。
   - 银行业务完整态：双边互转匹配、Remove & Redo 尾差联动、Bank Rules 编辑弹窗、Cash Coding 原子事务与乐观锁。
   - 基础税务与报表完整态：MJ/Bank 反向税额符号修复、Find & Recode 现金制隔离与 Tax Rate 支持、`bas.py` 免税映射修正、全报表 CSV 导出。
2. **Stage 2 核心扩展（下一阶段最具商业价值）：**
   - **Repeating Invoices / Bills**（高频自动出账）；
   - **Batch Payments (AU ABA `.aba` 文件导出)**（澳洲企业发批量供应商付款刚需）；
   - **Fixed Assets Register（固定资产台账 + 直线法/余额递减法月度折旧运行）**；
   - **Expense Claims（员工垫付费用报销提交/审批/付款）**；
   - **Multi-Currency 基础**（外币发票按日汇率记账及期末汇兑损益重估，需补充独立专项校验）。
3. **继续明确延后（Stage 3+ / 独立商业合作）：**
   - **Bank Feeds 商业直连**（Basiq / Yodlee CDR 牌照与单账户成本高）；
   - **ATO SBR / PLS 电子申报直连**（须通过 ATO DSP 安全与加密认证）；
   - **AU Payroll & STP Phase 2**（复杂 Fair Work 薪酬/休假/Superstream 法规风险）；
   - **Tracked Inventory** 与 **Xero App Store 第三方 OAuth 平台**。
