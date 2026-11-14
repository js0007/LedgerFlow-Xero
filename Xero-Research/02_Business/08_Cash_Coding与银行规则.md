# 08_Cash_Coding与银行规则（Cash Coding & Bank Rules）

## 1. 模块概述：这个模块解决什么问题？
如果一个零售店或外勤公司每月有 500 笔小额银行卡刷卡支出（每天停车费 `$12`、加油 `$85`、7-Eleven `$15`），在普通双栏对账页一条条点 500 次太慢了。Xero 发明了两个效率外挂：
- **Bank Rules（银行规则）：** 让电脑记住“只要对方名字包含 `7-Eleven`，就自动认出是公司，自动归进 `453 办公费 + GST on Expenses`”，把手动填写变成一键点 `OK`；
- **Cash Coding（类 Excel 批量对账）：** 把未对账流水像 Excel 表格一样一排排铺开，按规则套用或勾选 20 条同类的“停车费”，一秒全部记账并对账完成！

---

## 2. 基础知识先导：零基础也能懂的核心概念
- **Bank Rule 为什么能比银行流水更聪明？** 因为还能**按固定金额或比例自动分拆行**！例如每月电费扣款可能同时分摊 `60% 公司运营部` + `40% 仓库部`，或者某固定套餐扣款先抽走 `$20` 月费、剩下全部进流量费——银行规则可以在对账建议里帮你自动拆成多行会计分录！
- **Cash Coding 的适用禁区：** Cash Coding 是专门用来批量 **新建现金收支（Create Spend/Receive Money）** 的极速引擎；如果你需要把收款去匹配一张**以前开好的销售发票（Match Invoice）**，通常保留在标准 `Reconcile` 栏用 Match（Cash Coding 界面默认隐藏已有 Match 建议，除非你主动点 `Show lines with suggested matches`）。

---

## 3. 实际业务场景
> **案例（基于 Demo `!VD61z` 真实规则与 Cash Coding，`E42, E44`）：** 公司几乎每周都在 `7-Eleven` 和 `Central City Parking` 刷卡买日用和停车。会计建了一条 Spend Money Rule：条件 `Payee contains "Eleven"` -> 联系人为 `7-Eleven`，`100%` 归集到 `453 Office Expenses` + `GST on Expenses (10%)`。月底积压了 10 笔停车费和 7-Eleven 刷卡流水，打开 `Cash coding` 一眼扫过去全勾上，点一下 **`Save & Reconcile All`**，半分钟干完过去半天的活。

---

## 4. Xero 中的页面与操作路径
- **Bank Rules（`/app/.../bank-rules` & 编辑页 [E42](../evidence/pages/E42-demo-bank-rule-edit.webp)）：**
  - 三个分栏页签：`Spend money rules`、`Receive money rules`、`Transfer money rules`，支持鼠标**拖拽规则排序决定优先匹配顺序**。
  - **规则表单五步结构（实测 `E42`）：**
    1. *Apply a bank rule*：匹配模式选择 **`Any conditions match (OR)`** 或 **`All conditions match (AND)`**，添加多条过滤规则（字段可选 `Payee` / `Description` / `Amount` / `Reference` 等，条件含 `contains` / `equals` / `starts with` 等）；
    2. *Set the contact*：指定归属联系人（如 `7-Eleven`）；
    3. *Allocate line items*：上表格可加任意条**固定金额拆行（Fixed value line items）**；下表格将余下金额按**百分比（Percent line items，合计必须 `= 100.00%`）**拆分指定科目、税率与 Tracking 追踪标签；
    4. *Set the reference*：映射参考号来源；
    5. *Add rule details*：作用于 `All bank accounts` 或仅某个银行卡，起规则名并保存。
- **Cash Coding 网格页（`/Bank/FastCoding.aspx`，[E44](../evidence/pages/E44-demo-cash-coding.webp)）：**
  - 顶栏按钮：`Uncheck all`、`Discard changes`、`Apply rule`、`Show lines with suggested matches` 开关、`Save & Reconcile All`。
  - 电子表格列：`[复选框] | Date | Payee | Reference | Description | Account | Tax Rate | Tracking/Region | Spent | Received`。
  - 支持直接选多行同时下拉改 Account/Tax Rate 批填充（像 Excel 拖填一样）。

---

## 5. 核心业务规则
1. **规则按排位顺序优先命中：** 排在 1 号的规则一旦命中某条银行流水，就不再往下命中 2 号规则；
2. **百分比必须严格闭合 100.00%：** 规则编辑器要求比例分配表格各行百分比加总绝对等于 `100.00%`，防止钱凭空漏算或算多；
3. **Cash Coding 批过账校验：** 任何被勾选准备 `Save & Reconcile All` 的行，必须已经填写合法的 `Account` 和 `Tax Rate`（否则不能点保存并提示缺必填科目）。

---

## 6. 数据与会计影响
- 新建或调整 Bank Rule（或者仅仅在 Cash Coding 表格下拉改还没点保存）：**不产生会计分录**。
- 当你在 Cash Coding 勾选并点击 **`Save & Reconcile All`**（或在 Reconcile 页对 Rule 推荐点击 **`OK`**）：
  - 系统在同一个事务内批量生成对应数量的 `BankTransaction (CASHREC / CASHPAID)` 与不可变总账 `Journal`，如果是按规则多行拆分的，就按每行占比分别拆计税并生成多行 `JournalLine`，同时将这些银行流水全部更新为 `RECONCILED`。

---

## 7. 对独立产品复刻的借鉴要求
1. 实现支持 **Spend / Receive / Transfer 三类规则 + Any/All 条件 + Fixed 固定值 + 100% Percent 比例拆行** 的完整 Bank Rules 引擎，并在对账建议管道最前段自动生效！
2. 打造高还原度的 **Cash Coding 电子表格快速批录工作区**（含已命中 Rule 预高亮填充、多选批量赋科目/税率、单键 `Save & Reconcile All`）。
