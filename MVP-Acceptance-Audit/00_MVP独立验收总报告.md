# LedgerFlow AU — MVP 独立验收总报告

> **审查范围：** `D:\ai-work\au-faiw\xero调研`（`app/` 前后端与数据库、`Accounting-SaaS-Blueprint/`、`Xero-Research/`）  
> **审查原则：** 只审查、不改业务代码；严格区分 **[已验证]**（本轮独立自动化脚本 / 测试重跑 / 真实浏览器检查实证）、**[代码推断]**（静态调用链与 Schema 检查推断）与 **[待验证]**（缺官方细则确认或未做压测的场景）。  
> **基线结论时间：** 2026-11-15

---

## 1. 整体评价与真实完成度结论

**一句话结论：** LedgerFlow AU 不是“仅能跑通三笔账的 UI Demo”，它已经是一套**具备真实不可变总账内核、54 个 AU 标准会计科目、11 个 ATO 税率、商业单据/银行对账/手工分录/Simpler BAS/核心财务报表闭环的工程级单机 MVP 原型**；但它**距离可多租户对外运营的生产级 SaaS 会计软件仍有显著差距**，目前处于 **“内部财务内核原型可跑通（约 68% 核心会计流程完整） + 生产安全/并发治理/税务边界补洞阶段”**。

### 1.1 当前基线状态（任务 1 实测）

| 检查项 | 实测结果 | 证据与说明 |
|---|---|---|
| Git 版本基线 | **未建立 Git 仓库（高风险）** | 项目根目录无 `.git` 目录，无法追踪或回滚增量改动 **[已验证]** |
| 后端已有测试套件 | **`8 passed in 2.39s`**（退出码 `0`） | `app/.venv/Scripts/python.exe -m pytest -v -ra`，覆盖 SQLite 触发器、Rounding、Golden Suite 1/2 及常规流程 **[已验证]** |
| 前端 TypeScript 与构建 | **`tsc` 通过、`vite build` 1585 modules 通过（1.83s）** | 生成 `dist/index.html`、`dist/assets/index-*.css/js`，无编译错误 **[已验证]** |
| 干净环境独立启动 | **`create_app(fresh_db, bootstrap=True)` 成功** | 自动建库并初始化 `!W5gW!`（干净账套）与 `!VD61z`（Demo Company），Dashboard HTTP `200` **[已验证]** |
| 本轮独立审计脚本 | 18 项端到端会计与安全场景验证完成 | 隔离 `:memory:`/临时 SQLite 执行（`verify_audit.py`），检出 **12 项明确缺陷/行为缺口** **[已验证]** |
| 浏览器实测（Chrome DevTools） | 零 JS Console Error，覆盖未测页面与响应式检查 | 检出 Dashboard 未净额 Credit Note 差异（`$9,621.50` vs `$9,561.00`）、`READONLY` 按钮暴露及 500px 视口横向溢出（`scrollWidth=905`） **[已验证]** |

---

## 2. 六维成熟度评分

| 评估维度 | 完成度评分 | 客观定性 | 关键依据 |
|---|---|---|---|
| **总账内核与数据精度** | **85 / 100** | 扎实可用 | SQLite `BEFORE UPDATE/DELETE` 触发器物理锁死 `journals`/`journal_lines`/`audit_logs`；全链路 `*_cents` 整型分 + `Decimal ROUND_HALF_UP` 行级算税 **[已验证]** |
| **商业单据与收付款闭环** | **70 / 100** | 主干通畅、分支缺口 | Invoice/Bill/CN/Quote/PO、部分付款、Payment 冲销已通；缺 **Credit Note 现金退款、CN 解除核销、Draft 删除、Authorised 改单、Quote/PO 状态流转** **[已验证]** |
| **银行对账、规则与 Cash Coding** | **62 / 100** | 核心可演示、对账边界有账务漏洞 | Twin Balances/Rule 引擎/4 动作对账已做；但**跨行互转重复过账（双倍变动银行余额）**、**Remove & Redo 遗留微调分录**、**Cash Coding 批处理非原子+绕过 version** **[已验证]** |
| **AU Simpler BAS 与税务边界** | **55 / 100** | 主流场景对，异常方向与免税码有坑 | `G1/1A/1B/9`、Cash 按付款比例分摊及 Finalise 水印结构正确；但 **MJ 借方 OUTPUT / 贷方 INPUT、Bank RECEIVE+INPUT 税额符号错为正数**、`bas.py` `EXEMPTINPUT` 拼写错误导致免税支出漏计入内部 G10/G11 **[已验证]** |
| **财务报表与跨模块一致性** | **76 / 100** | 四大表勾稽强、Find & Recode 逻辑污染现金制 | Cross-FY 虚拟结转、负余额银行透支重分类、Demo 账套 AR/AP/TB/BS 严格平衡 **[已验证]**；但 **Find & Recode 改未付发票会污染 Cash P&L**、Dashboard AR 未扣减 Credit Note **[已验证]** |
| **多租户安全与 SaaS 生产底座** | **25 / 100** | 仅适合本地单机演示 | **完全无登录/Token 认证**（`get_actor` 默认取首行用户）、`POST /auth/switch-role` 可任意提权为 `ADVISER`、跨组织 `contactId` 注入可创建 Quote、先读后开启 `BEGIN IMMEDIATE` 存在并发竞态 **[已验证]** |

---

## 3. 核心优势设计（已验证保留资产）

在开始修复与二期演进前，以下 **6 项现有架构与会计设计**经审计证实符合企业级财务软件原则，后续不应破坏：

1. **物理级 Append-Only 不可变总账**（[accounting_core_sqlite.sql](file:///d:/ai-work/au-faiw/xero调研/Accounting-SaaS-Blueprint/schemas/accounting_core_sqlite.sql)）：`journals`、`journal_lines`、`audit_logs` 均由数据库触发器强制拦截 `UPDATE`/`DELETE`（`LEDGER_IMMUTABLE` / `AUDIT_IMMUTABLE`），任何纠错强制走独立冲销凭证。
2. **整型分（`*_cents`）与行级 `Decimal ROUND_HALF_UP` 算税**（[money.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/money.py)）：3 行 × `$33.35` Exclusive 10% GST 实测精确输出 `subTotal=100.05`、`totalTax=10.02`、`total=110.07` **[已验证]**。
3. **AU 54 科目表 + 47 手工日记账受控过滤 + 11 税率种子**（[seed.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/seed.py)）：精准隔离 `610`/`800`/`Bank`/`497`/`498`/`877` 等受控科目，防止破坏子账对账。
4. **跨财年 Balance Sheet 虚拟结转与负余额银行重分类**（[reports.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/reports.py#L238-L377)）：实测在 `2027-07-31` 查询新财年 BS 时，自动将 FY27 损益归入 `960 Retained Earnings`（`-190.00`）、CYE 归零，并将 `090` 负余额 `-$280.00` 重分类至流动负债 `Main Bank (Overdraft)`，保持 `Net Assets == Total Equity` **[已验证]**。
5. **Simpler BAS 锁表水位线机制**（[bas.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/bas.py#L242-L362)）：以 `max_journal_number` 快照留存已申报期，并在下期草稿自动抓出回溯补充的分录（Unfiled amounts）。
6. **幂等键载荷哈希校验**（[db.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/db.py) & [accounting_routes.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/routes/accounting_routes.py#L18-L26)）：实测同 `Idempotency-Key` 提交不同请求体时正确拦截返回 HTTP `409 IDEMPOTENCY_CONFLICT` **[已验证]**（仅存写入事务分离小瑕疵）。

---

## 4. 关键风险与阻断性问题汇总（Top 10）

| 优先级 | 问题 | 实测证据位置 | 严重程度 | 实际业务/系统影响 |
|---|---|---|---|---|
| **P0-1** | **无认证机制 + 任意接口提权至 `ADVISER`** | [core_routes.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/routes/core_routes.py#L19-L31), [#L70-L85](file:///d:/ai-work/au-faiw/xero调研/app/backend/routes/core_routes.py#L70-L85) | **致命** | 任何人可免认证读取全库，并直接调 `/auth/switch-role` 提权绕过 Soft Lock 与使用 Find & Recode **[已验证]** |
| **P0-2** | **银行互转（Transfer）双边对账重复记账** | [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L279-L318), [#L674-L717](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L674-L717) | **严重** | Bank A 转出选 Transfer 记一次账后，Bank B 收到转账未提示匹配且再次选 Transfer 会把两账户余额推成双倍（实测 `-500 -> -1000` / `+500 -> +1000`） **[已验证]** |
| **P0-3** | **Manual Journal 借方 `OUTPUT` / 贷方 `INPUT` 与 Bank `RECEIVE+INPUT` 税额符号错误** | [manual_journals.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/manual_journals.py#L133-L154), [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L490-L505) | **严重** | 反向含税调账或供应商现金退款在 BAS 中被当成正税额累加（实测 `1A` 错为 `+10`、`1B` 错为 `+10`） **[已验证]** |
| **P0-4** | **`Remove & Redo` 未冲销 Minor Adjustment 尾差调整分录** | [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L622-L640), [#L809-L824](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L809-L824) | **严重** | 对账微调 `$0.10` 后点 `Remove & Redo`，发票重开为 `$110.00` 但 `860 Rounding` 借方 `$0.10` 永久残留在总账 **[已验证]** |
| **P0-5** | **Find & Recode 重分类未付发票污染 Cash Basis 损益表** | [reports.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/reports.py#L105), [#L930](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/reports.py#L930) | **严重** | 未收款发票重分类 `200 -> 260` 后，Cash P&L 账目出现 `-$200` 与 `+$200` 虚假现金流水 **[已验证]** |
| **P0-6** | **跨组织 `contactId` 越权引用（部分端点缺 `org_id` 校验）** | [documents.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/documents.py#L903), [#L965](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/documents.py#L965), [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L520) | **高** | `!W5gW!` 创建 Quote 时传入 `!VD61z` 的 `contactId` 实测返回 HTTP `201`，跨租户数据泄漏 **[已验证]** |
| **P0-7** | **`bas.py` 存在 `"EXEMPTINPUT"` 幽灵税码拼写错误 + 回溯 Cash Credit Note 核销漏统计** | [bas.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/bas.py#L126), [#L195](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/bas.py#L195) | **高** | `EXEMPTEXPENSES`/`EXEMPTCAPITAL` 内部 `G10/G11` 恒为 `0`；Cash BAS 结账后回溯核销免税/含税单据在 Unfiled 中被静默跳过（实测 `unfiledIncludedCount=0`） **[已验证]** |
| **P0-8** | **Credit Note 无法现金退款 & 无法解除核销（Unallocate）** | [documents.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/documents.py#L736), [accounting_routes.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/routes/accounting_routes.py#L183) | **高** | 客户预付或超付产生的红字贷项单无法打款退款（`POST /payments` 返回 `404`），误核销后也无法撤回 **[已验证]** |
| **P0-9** | **Cash Coding 批量保存非原子性 + 忽略前端传入 `version`** | [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L725-L776) | **高** | 第 2 条报错 HTTP `422` 时第 1 条已提交为 `RECONCILED`，产生部分入账；且覆盖 DB 最新 `version` 破坏乐观锁 **[已验证]** |
| **P0-10** | **关键财务状态计算在 `BEGIN IMMEDIATE` 事务外预先读取（TOCTOU）** | [documents.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/documents.py#L735-L767), [banking.py](file:///d:/ai-work/au-faiw/xero调研/app/backend/services/banking.py#L549-L564) | **高** | 并发收款或并发对账时在锁外计算剩余欠款，高并发或迁移 PostgreSQL 时易触发超付或重入账 **[代码推断]** |

---

## 5. 第六部分核心问题独立回答

### 问题 1：现有的账务内核可信吗？有哪些必须修复的账务漏洞？
**结论：底层双分录与舍入内核可信（约 85% 信任度），但中上层“反向税务处理、银行特殊对账路径、Find & Recode 现金制联动、Dashboard AR 汇总”存在 6 处必须立即修复的账务漏洞。**
- 可信部分：SQLite `append-only` 触发器、`*_cents` + `Decimal HALF_UP`、普通 `ACCREC/ACCPAY/PAYMENT/BAS` 主线以及跨财年 BS/TB 虚拟结转均已实测准确 **[已验证]**。
- 必须修复的账务漏洞：
  1. 跨行互转 `TRANSFER` 双边对账重复入账（余额翻倍）**[已验证]**；
  2. Taxed Manual Journal 借方 `OUTPUT` / 贷方 `INPUT` 及 Bank `RECEIVE + INPUT` / `SPEND + OUTPUT` 的正负号缺失 **[已验证]**；
  3. `MATCH` 含 `Minor Adjustment` 后执行 `Remove & Redo` 遗留 `860 Rounding` 等尾差凭证 **[已验证]**；
  4. `Find & Recode` 改动未付发票导致 `RECODE` 分录错误进入 Cash Basis P&L **[已验证]**；
  5. `bas.py` 的 `EXEMPTINPUT` 幽灵税码映射失效与回溯期 Cash Credit Note 核销未进 Unfiled **[已验证]**；
  6. Dashboard 应收卡片未净额扣除 `ACCRECCREDIT`（实测 `$9,621.50` 与 Aged AR `$9,561.00` 相差 `$60.50`）**[已验证]**。

### 问题 2：前端界面和交互离真实 Xero 还有多远？是细节打磨问题，还是架构重建问题？
**结论：不是前端框架推倒重建问题，而是“前端契约对齐 + 路由/状态补全 + 细节打磨（约需 2~3 周重构补齐）”。**
- 视觉与结构上，React 18 + 顶部蓝色导航栏 + 卡片/表格密度 + `Match / Create / Transfer / Discuss` 绿底 `OK` 对账三栏已高度还原 Xero 信息架构 **[已验证]**。
- 真实差距集中在两类工程欠账：**（a）前后端接口/字段错位**（例如 COA 添加弹窗发送不被后端接受的 `OVERHEADS`、清空默认税率发 `null` 被后端 `COALESCE` 吃掉、`Archive Account` 误调 `DELETE` 接口）**[已验证]**；**（b）交互完整度与状态机缺口**（纯内存 `route` 切换导致刷新回首页及无浏览历史、Authorised 单据不能编辑、Posted MJ 被前端隐藏编辑按钮、Dashboard `READONLY` 未隐藏按钮、500px 窄屏横向溢出、BS/TB/BAS 缺 CSV 导出、时间筛选器硬编码 `2026-07-01`~`2027-06-30`）**[已验证]**。

### 问题 3：现有的技术架构能否直接演进为商业 SaaS？需要做哪些基础设施改造？
**结论：服务层业务模块化划分合理，可直接复用领域逻辑向商业 SaaS 演进，但当前数据库引擎（SQLite）、身份鉴权、请求上下文传递与并发模型不能直接上公网商业化，必须先完成 5 项底座改造。**
- 当前阻塞上线的底座问题：零鉴权认证（`get_actor` 查库首行用户）、`switch-role` 任意提权、部分接口跨组织 `contactId` 越权、SQLite 单机文件锁并发瓶颈、文件附件系统缺失、无备份/健康探针/限流 **[已验证]** / **[代码推断]**。
- 必做改造：引入真实 OIDC/JWT Auth + 会话与服务端 RBAC；迁移 PostgreSQL 16 + `org_id` 强制行级隔离（RLS）与 `SELECT ... FOR UPDATE` 悲观行锁；将所有读写计算收拢至同一事务边界（含幂等表写入）；接入对象存储（S3/R2）保存单据附件与定期冷备。

### 问题 4：Xero 哪些已研究功能现在还没有复刻？其中哪些是 Stage 2 必须补齐的，哪些仍应该继续延后？
- **对照 `Xero-Research/01_Xero全站产品功能地图.md`**：13 个产品大域中，**Stage 1 核心 8 大域**已复刻约 **75% 核心能力**，主要未复刻项集中在：**周期性发票/账单（Repeating Invoices/Bills）、批量付款文件（ABA Batch Payments）、多币种实时汇率与 FX Revaluation、Credit Note 现金退款与解除核销、银行规则修改与 Split 固定/百分比向导完整交互、Tracked Inventory、Fixed Assets、Projects、Expense Claims、AU Payroll / STP2、Bank Feeds、ATO SBR、App Store OAuth**。
- **Stage 2 必须补齐：** （1）**Stage 1 业务闭环补全**（CN 退款与解除核销、Repeating Invoices/Bills、Draft 删除、Authorised 编辑、Quote/PO 状态机与转单）；（2）**Expense Claims（员工报销与 `801` 科目联动）** 与 **Fixed Assets Register（固定资产卡片与月度折旧运行）**；（3）**多币种基础（含未实现汇兑损益测试）** 与 **ABA 批量付款导出**。
- **仍建议延后：** **Bank Feeds 商业直连（Yodlee/Basiq 需牌照与成本）、ATO SBR/PLS 报税直连（须 DSP 软件开发商认证）、AU Payroll STP Phase 2（合规法规极重）、完整 Tracked Inventory（需重做存货计价队列）、Xero App Store 开放 OAuth 生态**。

### 问题 5：当前测试体系是否足以支撑后续继续开发？存在哪些测试盲区？
**结论：远远不足。当前仅 8 个后端测试且完全没有前端与并发测试，不能作为安全回归护城河。**
- 当前仅有 3 个后端测试文件共 **8 个测试函数**（实测全部通过），覆盖主线 Happy Path 与 Golden Suite 1/2，**无任何 UI 自动化测试（Playwright/Vitest）、无任何并发竞态测试、无跨组织越权测试、无反向税务符号与 Remove & Redo 组合边界测试** **[已验证]**。在本轮审计中，正是这些未覆盖的边界暴露出 12 个真实漏洞。

### 问题 6：如果要长期维护和扩展这个项目，代码结构有哪些需要重构的地方？
1. **引入 Alembic 数据库迁移机制**（替代 `schema.sql` 一次性建表）；
2. **修复路由与服务层的职责边界**：统一将 `core_routes.py` 中直接写 SQL 的账户/税率/Contact 校验逻辑下沉到 `services/`，并建立统一请求 Schema 校验层（如 Pydantic/Marshmallow），杜绝 `KeyError` 抛出 HTTP `500` **[已验证]**；
3. **重整事务装饰器与幂等中间件**：将 `Idempotency-Key` 校验与写入纳入同一个 `atomic_tx(conn)` 原子事务中；
4. **前端拆解超长单文件组件**：`BankingReconcileView.tsx`（1547 行）、`ReportsAndBasView.tsx`（1273 行）、`AccountingWorkspaceView.tsx`（1265 行）已出现明显巨型组件倾向，需拆出独立 Hook、类型校验层及基于 `react-router` 的真实 URL 路由；
5. **消除前后端枚举/字段契约漂移**：自动或集中共享 AccountType、TaxCode、API Payload 类型定义。

### 问题 7：下一阶段最优先、投入产出比最高的 5 件事是什么？
1. **立即建立 Git 基线仓库 + 搭建完整自动化回归防线**：初始化 `.git` 基线提交，补齐前后端 CI、反向账务/多租户边界单元测试和 Playwright E2E，锁定现有成果 **[已验证]**；
2. **集中修复 P0 级 6 项账务核心漏洞**：互转匹配去重、MJ/Bank 反向税额正负号、Remove & Redo 尾差联动、Find & Recode 现金制隔离、`bas.py` `EXEMPTINPUT` 拼写与回溯期 CN 核销、Dashboard AR 扣减 Credit Note **[已验证]**；
3. **补齐生产认证、权限控制与多租户隔离底座**：接入真实 Auth、移除任意 `switch-role`、全面强制 `org_id` 资源外键校验、将读-改-写逻辑整体纳入事务 **[已验证]**；
4. **修复前后端契约错位并打通商业单据缺口生命周期**：修复 COA `OVERHEADS`/清空税率/归档接口错位，补全 Credit Note 退款与解除核销、Draft 删除、Authorised 编辑与 CSV 全表导出 **[已验证]**；
5. **启动 PostgreSQL 迁移适配与组件模块化拆分**：完成 SQL 方言/并发锁适配准备，引入 URL 路由并拆分前端千行大文件，为 Stage 2 功能扩展腾出干净可维护底座 **[代码推断]**。

---

## 6. 交付文档导航

1. [00_MVP独立验收总报告.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/00_MVP独立验收总报告.md) — 项目总体结论、成熟度评分与七大核心问题解答（本文档）
2. [01_会计业务正确性审计.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/01_会计业务正确性审计.md) — 16 个会计业务模块逐项分录/余额实测核查与缺陷清单
3. [02_跨模块账务一致性审计.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/02_跨模块账务一致性审计.md) — 8 条跨模块资金、总账与报表勾稽验证
4. [03_前端产品与交互验收.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/03_前端产品与交互验收.md) — 逐页检查结果、Live Browser 问题清单与 Xero 交互差距对比
5. [04_技术架构与生产化审计.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/04_技术架构与生产化审计.md) — 多租户、SQLite→PostgreSQL 迁移、事务并发、RBAC、备份及可维护性审计
6. [05_Xero功能覆盖与差距矩阵.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/05_Xero功能覆盖与差距矩阵.md) — 对照 Xero 全站 13 域功能地图的逐项覆盖分级矩阵
7. [06_下一阶段实施路线图.md](file:///d:/ai-work/au-faiw/xero调研/MVP-Acceptance-Audit/06_下一阶段实施路线图.md) — P0 / P1 / P2 优先级整改与 Stage 2 演进规划（含每项验收标准）
