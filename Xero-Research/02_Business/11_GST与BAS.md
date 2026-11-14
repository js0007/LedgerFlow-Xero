# 11_GST 与 AU Simpler BAS（Activity Statements）

## 1. 模块概述：这个模块解决什么问题？
在澳大利亚做生意，年营业额一旦达到 `$75,000 AUD` 就必须向税局（ATO）注册征收 **GST（商品及服务税，税率统一 10%）**。商家平时帮税局向客户多收 10%，自己采购进货付出的 10% 可以拿来抵扣，每季度或每月填一份 **BAS（Business Activity Statement）** 把差额多退少补交给 ATO。这个模块帮你自动算准 **`G1`、`1A`、`1B` 与最终应缴/退税额 `9`**，还能防止“上季度刚报完税，昨天又补进一张旧账单漏了报”。

---

## 2. 基础知识先导：零基础也能懂的核心概念
1. **10% GST 是替国家代收代付的过手钱（不是公司利润，也不是公司费用）：**
   - 你卖一件商品净价 `$100` + GST `$10` = 收客户 `$110`。那 `$10` 从来不是你赚的，它先躺在负债科目 **`820 GST`**（欠税局）里！
   - 你买台打印机净价 `$100` + GST `$10` = 付商家 `$110`。那 `$10` 你可以拿回来抵账，借方记入同一个 **`820 GST`** 冲掉部分欠税。
   - **月底结算差额：** 代收 `$10`（1A）- 可抵扣 `$10`（1B）= 净交 `$0`！
2. **Simpler BAS 到底是哪三个核心格？（ATO 对 <$10M 小微企业简化制度）**
   - **`G1`（Total sales，总销售额）：** 当期全部销售总和（Xero AU 默认以**含 GST 总额 `totalGross`** 展示，也可在 Settings 切换为不含 GST）。
   - **`1A`（GST on sales，销项 GST）：** 卖东西帮税局收的 10% GST（来自 `OUTPUT` 税码）。
   - **`1B`（GST on purchases，进项 GST）：** 买办公用品、房租、原料时别人票据里含的 10% GST（来自 `INPUT` 税码）。
   - **`Payment or Refund (Box 9)`：** `8A (=1A)` 减去 `8B (=1B)`。正数代表你要交税给 ATO，负数（带负号）代表 ATO 退钱给你！
   - 注意：**向 ATO 正式申报时各栏位金额统一取整数澳元（Whole dollars）**（`E28-NET` 实测确认）。
3. **AU 6 个 Active 税率怎么选？（实测 `E05` & `E06-NET`）**
   - `GST on Income (10%, OUTPUT)` -> 算入 `G1` 与 `1A`
   - `GST on Expenses (10%, INPUT)` -> 算入 `1B`
   - `GST Free Income (0%, EXEMPTOUTPUT)` -> 例如出口免税销售、部分生鲜食品：**算入 `G1` 总营业额，但 `1A = 0`**！
   - `GST Free Expenses (0%, EXEMPTEXPENSES)` -> 例如商业水费、免税银行费：`1B = 0`
   - `BAS Excluded (0%, BASEXCLUDED)` -> 发工资、老板投股本、银行内部转账、罚款：**既不进 `G1`，也不进 `1A` 和 `1B`！**（非常关键，发工资千万别误选成 GST Free！）
   - `GST on Imports (0%/特殊核对, GSTONIMPORTS)` -> 海关清关直缴 10% GST（直接走特殊进项抵扣）。

---

## 3. 实际业务场景（实测全套数字验证，`E24, E28, E35, E36`）
> **场景 A（Accruals 权责制 BAS）：** 本季度开出两张各含税 `$110` 的销售发票（总销售 `$220`、销项 GST `$20`），录入一张含税 `$110` 办公费用账单（进项 GST `$10`），另外有一张 `$55` 的采购费用退货单 `Supplier Credit Note`。**结果：** `G1 = 220`、`1A = 20`、`1B = 10 - 5 = 5`、`Payment 9 = 20 - 5 = $15`（应向税局交 `$15`）。  
> **场景 B（Cash 收付制 BAS 陷阱破除，`E35`）：** 开出一张 `$220` 的销售发票后，客户只先付了 `$55`；又开了一张 `$55` 销售 Credit Note **但忘记点 Allocate 核销**。切到 Cash Basis 查看 BAS：`G1 = 55`、`1A = 5`——那 `$55` Credit Note 在 **没 Allocate 前绝对不抵扣 `1A`**！直到你完成 Allocate 核销，下一瞬间 BAS 立刻少收那 `$5`！

---

## 4. Xero 中的页面与操作路径
- **入口：** `Tax -> Activity statements`（`/app/.../bas`，[E20](../evidence/pages/E20-demo-bas-summary.webp)、[E28](../evidence/pages/E28b-mvp-bas-transactions.webp)）与 `Tax -> Activity Statement settings`（`/app/.../bas/bas-settings`）。
- **页面区块：**
  - 状态列表页：`Needs attention`（当期草稿/待办）vs `Completed`（已定稿归档）；未连接税局时顶部显示 `Not connected to ATO`。
  - **Summary Tab：** 按 ATO 表格样式列出 `G1 Total sales`、`1A GST on sales`、`1B GST on purchases`、`8A`、`8B`、`9 Net payment / refund`。
  - **Transactions by tax rate Tab：** 下钻列表，把每一笔贡献了 `G1/1A/1B` 的发票、账单、付款、银行现结按 `Tax Rate` 分组摊开给你审计核对。
  - **Transactions by BAS field Tab：** 按 `G1 / 1A / 1B` 格位逐行核对。
  - **底部主按钮：** `Export` 与 **`Finalise statement`**。

---

## 5. 核心业务规则（含独创的“水位线 Unfiled amounts”防漏机制）
1. **单调递增 `JournalNumber` 水位线（`E28-NET` 实测抓包解密）：**
   - 当你点击 **`Finalise`** 定稿 Q1（1 月–3 月）BAS 时，系统会记录截至此刻总账写入到的最大分录号 `maxJournalNumber`（例如 `#150`）。
   - 如果下个月老板翻出一张遗漏的 3 月加油收据补录入账（它落到了 3 月日期，但新产生的分录号是 `#180 > 150`）——当系统计算 Q2 BAS（4 月–6 月）或重看期间汇总时，它仅需扫描 `JournalDate < 本期起点 AND JournalNumber > 150`，立刻捕获这笔迟到交易，自动列在 **`Previous periods unfiled amounts（上期未申报调整额）`** 里，确保永不漏税也不重报！
2. **Whole Dollars 取整：** 每个栏位计算底层精确到分（0.01），汇总展示与申报定稿时按澳洲规则截断/舍入为整元 AUD。

---

## 6. 数据与会计影响
- 点击 **`Finalise BAS`**：将当期快照与 `maxJournalNumber` 冻结保存为不可更改的 `FINALISED` 记录。
- 实际把税款打给 ATO 时：做一笔 **`Spend Money`（银行支出 -> 科目选 `820 GST`，税码选 `BAS Excluded`）**，把负债 `820 GST` 余额清零——记住给税局交税**绝对不再产生 `1B` 进项抵扣**！

---

## 7. 对独立产品复刻的借鉴要求
1. 必须忠实复刻 `Accounting Method (Accrual vs Cash)` + `G1 Mode (Inclusive vs Exclusive)` + **Whole Dollar Output** + **Accrual 靠 `journal_lines` 驱动 vs Cash 靠 `payments + credit_note_allocations` 按行比例拆算驱动**。
2. 完整实现 **`Finalise BAS` 状态快照与 `max_journal_number` 水位线检测引擎**，在 UI 清晰高亮展示 `Unfiled amounts`！
