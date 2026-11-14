import { Fragment, useEffect, useState } from "react";
import { AlertCircle, BarChart3, CheckCircle2, Download, FileText, Lock, RefreshCw } from "lucide-react";
import { api, fmtAud } from "../api";
import type { AccountItem, TrackingCategory, UserRole } from "../types";
import type { RouteKey } from "./TopNav";

interface PnlRow {
  accountId: string;
  code: string | null;
  name: string;
  amount: string;
}

interface PnlData {
  fromDate: string;
  toDate: string;
  basis: string;
  sections: {
    tradingIncome: PnlRow[];
    costOfSales: PnlRow[];
    otherIncome: PnlRow[];
    operatingExpenses: PnlRow[];
  };
  totals: {
    tradingIncome: string;
    costOfSales: string;
    grossProfit: string;
    otherIncome: string;
    operatingExpenses: string;
    netProfit: string;
  };
}

interface BsRow {
  accountId: string | null;
  code: string | null;
  name: string;
  amount: string;
  reclassifiedOverdraft?: boolean;
}

interface BsData {
  asOfDate: string;
  currentFyStart: string;
  sections: {
    bank: BsRow[];
    currentAssets: BsRow[];
    fixedAssets: BsRow[];
    currentLiabilities: BsRow[];
    nonCurrentLiabilities: BsRow[];
    equity: BsRow[];
  };
  totals: {
    totalBank: string;
    totalCurrentAssets: string;
    totalFixedAssets: string;
    totalAssets: string;
    totalCurrentLiabilities: string;
    totalNonCurrentLiabilities: string;
    totalLiabilities: string;
    netAssets: string;
    totalEquity: string;
    isBalanced: boolean;
  };
}

interface TbData {
  asOfDate: string;
  currentFyStart: string;
  rows: {
    accountId: string;
    code: string | null;
    name: string;
    accountType: string;
    ytdDebit: string;
    ytdCredit: string;
    debit: string;
    credit: string;
  }[];
  totalDebit: string;
  totalCredit: string;
  isBalanced: boolean;
}

interface JournalReportItem {
  id: string;
  journalNumber: number;
  journalDate: string;
  sourceType: string;
  reference: string | null;
  narration: string;
  lines: {
    lineNo: number;
    accountCode: string | null;
    accountName: string;
    description: string | null;
    debit: string;
    credit: string;
    taxTypeCode: string | null;
  }[];
}

interface AccountTxGroup {
  accountId: string;
  accountCode: string | null;
  accountName: string;
  totalDebit: string;
  totalCredit: string;
  netMovement: string;
  transactions: {
    journalNumber: number;
    date: string;
    sourceType: string;
    contactName: string | null;
    reference: string | null;
    description: string | null;
    taxTypeCode: string | null;
    debit: string;
    credit: string;
  }[];
}

interface AgedData {
  reportKind: string;
  asOfDate: string;
  agingBy: string;
  rows: {
    contactId: string;
    contactName: string;
    current: string;
    lt1m: string;
    m1: string;
    m2: string;
    m3: string;
    older: string;
    total: string;
    items: { invoiceNumber: string; invoiceType: string; issueDate: string; dueDate: string; bucket: string; outstanding: string }[];
  }[];
  totals: { current: string; lt1m: string; m1: string; m2: string; m3: string; older: string; total: string };
}

interface CashFlowData {
  days: number;
  currentCash: string;
  expectedInflows: string;
  expectedOutflows: string;
  projectedEndBalance: string;
  upcomingTransactions: {
    invoiceId: string;
    invoiceNumber: string;
    contactName: string;
    dueDate: string;
    direction: "INFLOW" | "OUTFLOW";
    amount: string;
    isOverdue: boolean;
  }[];
}

interface BasStatementData {
  periodStart: string;
  periodEnd: string;
  accountingMethod: string;
  g1Mode: string;
  status: "DRAFT" | "FINALISED";
  finalisedAt?: string;
  minJournalNumber: number | null;
  maxJournalNumber: number | null;
  previousWatermark: number | null;
  unfiledIncludedCount: number;
  labels: { G1: string; G10: string; G11: string; "1A": string; "1B": string; "8A": string; "8B": string; Payment9: string };
  byTaxRate: { taxCode: string; taxName: string; netAmount: string; taxAmount: string; grossAmount: string; count: number }[];
  transactions: {
    date: string;
    journalNumber: number | null;
    sourceType: string;
    reference: string | null;
    description: string | null;
    taxCode: string;
    taxName: string;
    netAmount: string;
    taxAmount: string;
    grossAmount: string;
    isUnfiledPriorPeriod: boolean;
  }[];
}

interface BasHistoryRow {
  id: string;
  period_start: string;
  period_end: string;
  accounting_method: string;
  max_journal_number: number | null;
  g1_total_sales_dollars: number;
  gst_1a_sales_dollars: number;
  gst_1b_purchases_dollars: number;
  net_payment_9_dollars: number;
  unfiled_included_count: number;
  status: string;
  finalised_at: string;
}

interface Props {
  orgId: string;
  route: RouteKey;
  role: UserRole;
  onNavigate: (r: RouteKey) => void;
  onToast: (type: "success" | "error" | "info", msg: string) => void;
}

export function ReportsAndBasView({ orgId, route, role, onNavigate, onToast }: Props) {
  const canWrite = role !== "READONLY";
  const today = new Date().toISOString().slice(0, 10);

  const [fromDate, setFromDate] = useState("2026-07-01");
  const [toDate, setToDate] = useState(today < "2026-12-31" ? "2027-06-30" : today);
  const [asOfDate, setAsOfDate] = useState(today < "2026-11-30" ? "2026-12-31" : today);
  const [pnlBasis, setPnlBasis] = useState<"ACCRUAL" | "CASH">("ACCRUAL");
  const [trackingOptId, setTrackingOptId] = useState("");
  const [agingBy, setAgingBy] = useState<"DUE_DATE" | "ISSUE_DATE">("DUE_DATE");
  const [cfDays, setCfDays] = useState(30);
  const [accFilterId, setAccFilterId] = useState("");

  // AU BAS Quarter defaults
  const [basFrom, setBasFrom] = useState("2026-10-01");
  const [basTo, setBasTo] = useState("2026-12-31");

  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [tracking, setTracking] = useState<TrackingCategory[]>([]);
  const [pnl, setPnl] = useState<PnlData | null>(null);
  const [bs, setBs] = useState<BsData | null>(null);
  const [tb, setTb] = useState<TbData | null>(null);
  const [journals, setJournals] = useState<JournalReportItem[]>([]);
  const [accTx, setAccTx] = useState<AccountTxGroup[]>([]);
  const [aged, setAged] = useState<AgedData | null>(null);
  const [expandedContact, setExpandedContact] = useState<Record<string, boolean>>({});
  const [cashFlow, setCashFlow] = useState<CashFlowData | null>(null);
  const [bas, setBas] = useState<BasStatementData | null>(null);
  const [basHistory, setBasHistory] = useState<BasHistoryRow[]>([]);

  async function loadMeta() {
    const [accs, tks] = await Promise.all([
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts`),
      api.get<TrackingCategory[]>(`/orgs/${orgId}/tracking-categories`),
    ]);
    setAccounts(accs);
    setTracking(tks);
  }

  async function runReport() {
    try {
      if (route === "profit-and-loss") {
        const qs = new URLSearchParams({ from: fromDate, to: toDate, basis: pnlBasis });
        if (trackingOptId) qs.set("trackingOptionId", trackingOptId);
        setPnl(await api.get<PnlData>(`/orgs/${orgId}/reports/profit-and-loss?${qs.toString()}`));
      } else if (route === "balance-sheet") {
        setBs(await api.get<BsData>(`/orgs/${orgId}/reports/balance-sheet?date=${asOfDate}`));
      } else if (route === "trial-balance") {
        setTb(await api.get<TbData>(`/orgs/${orgId}/reports/trial-balance?date=${asOfDate}`));
      } else if (route === "journal-report") {
        setJournals(await api.get<JournalReportItem[]>(`/orgs/${orgId}/reports/journals?from=${fromDate}&to=${toDate}`));
      } else if (route === "account-transactions") {
        const qs = new URLSearchParams({ from: fromDate, to: toDate });
        if (accFilterId) qs.set("accountId", accFilterId);
        const res = await api.get<{ accounts: AccountTxGroup[] }>(`/orgs/${orgId}/reports/account-transactions?${qs.toString()}`);
        setAccTx(res.accounts);
      } else if (route === "aged-receivables" || route === "aged-payables") {
        const ep = route === "aged-receivables" ? "aged-receivables" : "aged-payables";
        setAged(await api.get<AgedData>(`/orgs/${orgId}/reports/${ep}?date=${asOfDate}&agingBy=${agingBy}`));
      } else if (route === "cash-flow") {
        setCashFlow(await api.get<CashFlowData>(`/orgs/${orgId}/analytics/cash-flow?days=${cfDays}`));
      } else if (route === "simpler-bas") {
        const [st, hist] = await Promise.all([
          api.get<BasStatementData>(`/orgs/${orgId}/bas/statement?from=${basFrom}&to=${basTo}`),
          api.get<BasHistoryRow[]>(`/orgs/${orgId}/bas/history`),
        ]);
        setBas(st);
        setBasHistory(hist);
      }
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  useEffect(() => {
    loadMeta()
      .then(() => runReport())
      .catch((e: Error) => onToast("error", e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, route]);

  function exportSimpleCsv(filename: string, headers: string[], rows: (string | number | null | undefined)[][]) {
    const csv = [headers.join(","), ...rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function finaliseBas() {
    try {
      await api.post(`/orgs/${orgId}/bas/statement/finalise`, { from: basFrom, to: basTo });
      onToast("success", `Finalised & locked AU Simpler BAS snapshot (${basFrom} .. ${basTo}).`);
      await runReport();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // === REPORTS HUB ===
  if (route === "reports-hub") {
    const groups: { title: string; items: { route: RouteKey; name: string; desc: string }[] }[] = [
      {
        title: "Financial",
        items: [
          { route: "profit-and-loss", name: "Profit and Loss", desc: "Accrual & Cash basis, Tracking filter" },
          { route: "balance-sheet", name: "Balance Sheet", desc: "Dynamic FY Earnings & Overdraft Reclass" },
          { route: "cash-flow", name: "Short-term Cash Flow", desc: "Projected cash inflows & outflows" },
        ],
      },
      {
        title: "Tax & Compliance (AU)",
        items: [
          { route: "simpler-bas", name: "Activity Statement (Simpler BAS)", desc: "Labels G1, 1A, 1B, 9, Unfiled watermark" },
        ],
      },
      {
        title: "Payables & Receivables",
        items: [
          { route: "aged-receivables", name: "Aged Receivables Summary & Detail", desc: "6-bucket aging + Unallocated credits" },
          { route: "aged-payables", name: "Aged Payables Summary & Detail", desc: "6-bucket aging by Due / Issue Date" },
        ],
      },
      {
        title: "Accounting & General Ledger",
        items: [
          { route: "trial-balance", name: "Trial Balance", desc: "YTD Debits/Credits + Retained Earnings rollover" },
          { route: "journal-report", name: "Journal Report", desc: "Chronological immutable GL journals" },
          { route: "account-transactions", name: "Account Transactions", desc: "Ledger movement grouped by account" },
        ],
      },
    ];
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reporting</div>
            <h1 className="x-page-title">Reports</h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-grid-2">
            {groups.map((g) => (
              <div key={g.title} className="x-card">
                <div className="x-card-header">
                  <div className="x-card-title">{g.title}</div>
                </div>
                <div className="x-card-body" style={{ display: "grid", gap: 8 }}>
                  {g.items.map((item) => (
                    <button
                      key={item.route}
                      className="x-menu-item"
                      style={{ border: "1px solid #eef1f5", padding: "10px 12px" }}
                      onClick={() => onNavigate(item.route)}
                    >
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 13.5 }}>{item.name}</div>
                        <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{item.desc}</div>
                      </div>
                      <FileText size={16} color="var(--xui-nav-blue)" />
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </main>
      </>
    );
  }

  // === PROFIT AND LOSS ===
  if (route === "profit-and-loss") {
    const track1 = tracking[0];
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Profit and Loss</div>
            <h1 className="x-page-title">Profit and Loss</h1>
          </div>
          {pnl && (
            <button
              className="x-btn"
              onClick={() =>
                exportSimpleCsv(
                  "profit-and-loss.csv",
                  ["Section", "Code", "Account", "Amount AUD"],
                  [
                    ...pnl.sections.tradingIncome.map((r) => ["Trading Income", r.code, r.name, r.amount]),
                    ...pnl.sections.costOfSales.map((r) => ["Cost of Sales", r.code, r.name, r.amount]),
                    ...pnl.sections.otherIncome.map((r) => ["Other Income", r.code, r.name, r.amount]),
                    ...pnl.sections.operatingExpenses.map((r) => ["Operating Expenses", r.code, r.name, r.amount]),
                  ]
                )
              }
            >
              <Download size={14} /> Export CSV
            </button>
          )}
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 16 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div className="x-field">
                <label>From</label>
                <input type="date" className="x-input" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
              </div>
              <div className="x-field">
                <label>To</label>
                <input type="date" className="x-input" value={toDate} onChange={(e) => setToDate(e.target.value)} />
              </div>
              <div className="x-field">
                <label>Accounting Basis</label>
                <select className="x-select" value={pnlBasis} onChange={(e) => setPnlBasis(e.target.value as "ACCRUAL" | "CASH")}>
                  <option value="ACCRUAL">Accrual Basis</option>
                  <option value="CASH">Cash Basis</option>
                </select>
              </div>
              {track1 && (
                <div className="x-field">
                  <label>{track1.name}</label>
                  <select className="x-select" value={trackingOptId} onChange={(e) => setTrackingOptId(e.target.value)}>
                    <option value="">All {track1.name}</option>
                    {track1.options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <button className="x-btn x-btn-primary" onClick={runReport}>
                <RefreshCw size={14} /> Update
              </button>
            </div>
          </div>
          {pnl && (
            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">
                  {pnl.fromDate} to {pnl.toDate} ({pnl.basis} Basis)
                </div>
              </div>
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th className="num">Amount (AUD)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ background: "#f4f6fa", fontWeight: 700 }}>
                    <td colSpan={2}>Trading Income</td>
                  </tr>
                  {pnl.sections.tradingIncome.map((r) => (
                    <tr key={r.accountId}>
                      <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                      <td className="num">{fmtAud(r.amount)}</td>
                    </tr>
                  ))}
                  <tr style={{ fontWeight: 700 }}>
                    <td>Total Trading Income</td>
                    <td className="num">{fmtAud(pnl.totals.tradingIncome)}</td>
                  </tr>

                  <tr style={{ background: "#f4f6fa", fontWeight: 700 }}>
                    <td colSpan={2}>Less Cost of Sales</td>
                  </tr>
                  {pnl.sections.costOfSales.map((r) => (
                    <tr key={r.accountId}>
                      <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                      <td className="num">{fmtAud(r.amount)}</td>
                    </tr>
                  ))}
                  <tr style={{ fontWeight: 700, background: "#eef5ff" }}>
                    <td>Gross Profit</td>
                    <td className="num">{fmtAud(pnl.totals.grossProfit)}</td>
                  </tr>

                  {pnl.sections.otherIncome.length > 0 && (
                    <>
                      <tr style={{ background: "#f4f6fa", fontWeight: 700 }}>
                        <td colSpan={2}>Plus Other Income</td>
                      </tr>
                      {pnl.sections.otherIncome.map((r) => (
                        <tr key={r.accountId}>
                          <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                          <td className="num">{fmtAud(r.amount)}</td>
                        </tr>
                      ))}
                    </>
                  )}

                  <tr style={{ background: "#f4f6fa", fontWeight: 700 }}>
                    <td colSpan={2}>Less Operating Expenses</td>
                  </tr>
                  {pnl.sections.operatingExpenses.map((r) => (
                    <tr key={r.accountId}>
                      <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                      <td className="num">{fmtAud(r.amount)}</td>
                    </tr>
                  ))}
                  <tr style={{ fontWeight: 700 }}>
                    <td>Total Operating Expenses</td>
                    <td className="num">{fmtAud(pnl.totals.operatingExpenses)}</td>
                  </tr>

                  <tr style={{ fontWeight: 800, fontSize: 15, background: "#e6f6ec" }}>
                    <td>Net Profit</td>
                    <td className="num">{fmtAud(pnl.totals.netProfit)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </main>
      </>
    );
  }

  // === BALANCE SHEET ===
  if (route === "balance-sheet") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Balance Sheet</div>
            <h1 className="x-page-title">Balance Sheet</h1>
          </div>
          {bs && (
            <span className={`x-badge ${bs.totals.isBalanced ? "green" : "red"}`}>
              {bs.totals.isBalanced ? "Assets - Liabilities = Equity (Balanced)" : "Out of Balance"}
            </span>
          )}
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 16 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
              <div className="x-field">
                <label>As at Date</label>
                <input type="date" className="x-input" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
              </div>
              <button className="x-btn x-btn-primary" onClick={runReport}>
                <RefreshCw size={14} /> Update
              </button>
              {bs && (
                <div style={{ fontSize: 12.5, color: "var(--xui-ink-muted)", paddingBottom: 6 }}>
                  AU Financial Year Start: <strong>{bs.currentFyStart}</strong>
                </div>
              )}
            </div>
          </div>

          {bs && (
            <div className="x-card">
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th className="num">As at {bs.asOfDate}</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { title: "Bank", rows: bs.sections.bank, totLabel: "Total Bank", tot: bs.totals.totalBank },
                    { title: "Current Assets", rows: bs.sections.currentAssets, totLabel: "Total Current Assets", tot: bs.totals.totalCurrentAssets },
                    { title: "Fixed Assets", rows: bs.sections.fixedAssets, totLabel: "Total Fixed Assets", tot: bs.totals.totalFixedAssets },
                  ].map((sec) => (
                    <Fragment key={sec.title}>
                      {sec.rows.length > 0 && (
                        <>
                          <tr style={{ background: "#f4f6fa", fontWeight: 700 }}><td colSpan={2}>{sec.title}</td></tr>
                          {sec.rows.map((r, i) => (
                            <tr key={`${sec.title}-${i}`}>
                              <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                              <td className="num">{fmtAud(r.amount)}</td>
                            </tr>
                          ))}
                          <tr style={{ fontWeight: 700 }}><td>{sec.totLabel}</td><td className="num">{fmtAud(sec.tot)}</td></tr>
                        </>
                      )}
                    </Fragment>
                  ))}
                  <tr style={{ fontWeight: 800, background: "#eef5ff" }}>
                    <td>Total Assets</td>
                    <td className="num">{fmtAud(bs.totals.totalAssets)}</td>
                  </tr>

                  {bs.sections.currentLiabilities.length > 0 && (
                    <>
                      <tr style={{ background: "#f4f6fa", fontWeight: 700 }}><td colSpan={2}>Current Liabilities</td></tr>
                      {bs.sections.currentLiabilities.map((r, i) => (
                        <tr key={`cl-${i}`}>
                          <td style={{ paddingLeft: 24 }}>
                            {r.code ? `${r.code} - ` : ""}{r.name}{" "}
                            {r.reclassifiedOverdraft && <span className="x-badge amber">Negative Bank Overdraft Reclass</span>}
                          </td>
                          <td className="num">{fmtAud(r.amount)}</td>
                        </tr>
                      ))}
                      <tr style={{ fontWeight: 700 }}><td>Total Current Liabilities</td><td className="num">{fmtAud(bs.totals.totalCurrentLiabilities)}</td></tr>
                    </>
                  )}

                  {bs.sections.nonCurrentLiabilities.length > 0 && (
                    <>
                      <tr style={{ background: "#f4f6fa", fontWeight: 700 }}><td colSpan={2}>Non-current Liabilities</td></tr>
                      {bs.sections.nonCurrentLiabilities.map((r, i) => (
                        <tr key={`ncl-${i}`}>
                          <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                          <td className="num">{fmtAud(r.amount)}</td>
                        </tr>
                      ))}
                    </>
                  )}

                  <tr style={{ fontWeight: 800 }}>
                    <td>Total Liabilities</td>
                    <td className="num">{fmtAud(bs.totals.totalLiabilities)}</td>
                  </tr>
                  <tr style={{ fontWeight: 800, background: "#e6f6ec" }}>
                    <td>Net Assets</td>
                    <td className="num">{fmtAud(bs.totals.netAssets)}</td>
                  </tr>

                  <tr style={{ background: "#f4f6fa", fontWeight: 700 }}><td colSpan={2}>Equity</td></tr>
                  {bs.sections.equity.map((r, i) => (
                    <tr key={`eq-${i}`}>
                      <td style={{ paddingLeft: 24 }}>{r.code ? `${r.code} - ` : ""}{r.name}</td>
                      <td className="num">{fmtAud(r.amount)}</td>
                    </tr>
                  ))}
                  <tr style={{ fontWeight: 800, background: "#e6f6ec" }}>
                    <td>Total Equity</td>
                    <td className="num">{fmtAud(bs.totals.totalEquity)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </main>
      </>
    );
  }

  // === TRIAL BALANCE ===
  if (route === "trial-balance") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Trial Balance</div>
            <h1 className="x-page-title">Trial Balance</h1>
          </div>
          {tb && (
            <span className={`x-badge ${tb.isBalanced ? "green" : "red"}`}>
              {tb.isBalanced ? "Debits = Credits (Balanced)" : "Imbalanced"}
            </span>
          )}
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 16 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
              <div className="x-field">
                <label>As at Date</label>
                <input type="date" className="x-input" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
              </div>
              <button className="x-btn x-btn-primary" onClick={runReport}>
                <RefreshCw size={14} /> Update
              </button>
            </div>
          </div>
          {tb && (
            <div className="x-card">
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Account</th>
                    <th>Account Type</th>
                    <th className="num">YTD Debit</th>
                    <th className="num">YTD Credit</th>
                    <th className="num">Debit Balance</th>
                    <th className="num">Credit Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {tb.rows.map((r) => (
                    <tr key={r.accountId}>
                      <td style={{ fontWeight: 700 }}>{r.code || "-"}</td>
                      <td>{r.name}</td>
                      <td>{r.accountType}</td>
                      <td className="num">{fmtAud(r.ytdDebit)}</td>
                      <td className="num">{fmtAud(r.ytdCredit)}</td>
                      <td className="num">{parseFloat(r.debit) !== 0 ? fmtAud(r.debit) : ""}</td>
                      <td className="num">{parseFloat(r.credit) !== 0 ? fmtAud(r.credit) : ""}</td>
                    </tr>
                  ))}
                  <tr style={{ fontWeight: 800, background: "#eef5ff" }}>
                    <td colSpan={5}>Total</td>
                    <td className="num">{fmtAud(tb.totalDebit)}</td>
                    <td className="num">{fmtAud(tb.totalCredit)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </main>
      </>
    );
  }

  // === JOURNAL REPORT ===
  if (route === "journal-report") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Journal Report</div>
            <h1 className="x-page-title">Journal Report ({journals.length} immutable journals)</h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 14 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
              <div className="x-field">
                <label>From</label>
                <input type="date" className="x-input" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
              </div>
              <div className="x-field">
                <label>To</label>
                <input type="date" className="x-input" value={toDate} onChange={(e) => setToDate(e.target.value)} />
              </div>
              <button className="x-btn x-btn-primary" onClick={runReport}>
                Update
              </button>
            </div>
          </div>
          {journals.map((j) => (
            <div key={j.id} className="x-card" style={{ marginBottom: 12 }}>
              <div className="x-card-header">
                <div>
                  <strong>Journal #{j.journalNumber}</strong> — {j.narration}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <span className="x-badge blue">{j.sourceType}</span>
                  <span style={{ color: "var(--xui-ink-muted)" }}>{j.journalDate}</span>
                </div>
              </div>
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Description</th>
                    <th>Tax</th>
                    <th className="num">Debit</th>
                    <th className="num">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {j.lines.map((l) => (
                    <tr key={l.lineNo}>
                      <td>{l.accountCode ? `${l.accountCode} - ` : ""}{l.accountName}</td>
                      <td>{l.description || "-"}</td>
                      <td>{l.taxTypeCode || "-"}</td>
                      <td className="num">{parseFloat(l.debit) > 0 ? fmtAud(l.debit) : ""}</td>
                      <td className="num">{parseFloat(l.credit) > 0 ? fmtAud(l.credit) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </main>
      </>
    );
  }

  // === ACCOUNT TRANSACTIONS ===
  if (route === "account-transactions") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Account Transactions</div>
            <h1 className="x-page-title">Account Transactions</h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 14 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div className="x-field" style={{ minWidth: 260 }}>
                <label>Account</label>
                <select className="x-select" value={accFilterId} onChange={(e) => setAccFilterId(e.target.value)}>
                  <option value="">All active accounts with transactions</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} - {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="x-field">
                <label>From</label>
                <input type="date" className="x-input" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
              </div>
              <div className="x-field">
                <label>To</label>
                <input type="date" className="x-input" value={toDate} onChange={(e) => setToDate(e.target.value)} />
              </div>
              <button className="x-btn x-btn-primary" onClick={runReport}>
                Update
              </button>
            </div>
          </div>

          {accTx.map((grp) => (
            <div key={grp.accountId} className="x-card" style={{ marginBottom: 14 }}>
              <div className="x-card-header">
                <div className="x-card-title">
                  {grp.accountCode ? `${grp.accountCode} - ` : ""}{grp.accountName}
                </div>
                <div>
                  Net Movement: <strong>{fmtAud(grp.netMovement)}</strong>
                </div>
              </div>
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Source</th>
                    <th>Contact</th>
                    <th>Description / Ref</th>
                    <th className="num">Debit</th>
                    <th className="num">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {grp.transactions.map((t, idx) => (
                    <tr key={idx}>
                      <td>{t.date}</td>
                      <td>
                        <span className="x-badge">{t.sourceType} #{t.journalNumber}</span>
                      </td>
                      <td>{t.contactName || "-"}</td>
                      <td>{t.description || t.reference || "-"}</td>
                      <td className="num">{parseFloat(t.debit) > 0 ? fmtAud(t.debit) : ""}</td>
                      <td className="num">{parseFloat(t.credit) > 0 ? fmtAud(t.credit) : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </main>
      </>
    );
  }

  // === AGED RECEIVABLES / PAYABLES ===
  if (route === "aged-receivables" || route === "aged-payables") {
    const isAr = route === "aged-receivables";
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; {isAr ? "Aged Receivables" : "Aged Payables"}</div>
            <h1 className="x-page-title">{isAr ? "Aged Receivables Summary & Detail" : "Aged Payables Summary & Detail"}</h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 14 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
              <div className="x-field">
                <label>As at Date</label>
                <input type="date" className="x-input" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
              </div>
              <div className="x-field">
                <label>Age by</label>
                <select className="x-select" value={agingBy} onChange={(e) => setAgingBy(e.target.value as "DUE_DATE" | "ISSUE_DATE")}>
                  <option value="DUE_DATE">Due Date</option>
                  <option value="ISSUE_DATE">Invoice / Bill Date</option>
                </select>
              </div>
              <button className="x-btn x-btn-primary" onClick={runReport}>
                Update
              </button>
            </div>
          </div>

          {aged && (
            <div className="x-card">
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Contact</th>
                    <th className="num">Current</th>
                    <th className="num">&lt; 1 Month</th>
                    <th className="num">1 Month</th>
                    <th className="num">2 Months</th>
                    <th className="num">3 Months</th>
                    <th className="num">Older</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {aged.rows.map((r) => (
                    <Fragment key={r.contactId}>
                      <tr
                        className="clickable"
                        onClick={() => setExpandedContact((p) => ({ ...p, [r.contactId]: !p[r.contactId] }))}
                      >
                        <td style={{ fontWeight: 700, color: "var(--xui-nav-blue)" }}>{r.contactName}</td>
                        <td className="num">{fmtAud(r.current)}</td>
                        <td className="num">{fmtAud(r.lt1m)}</td>
                        <td className="num">{fmtAud(r.m1)}</td>
                        <td className="num">{fmtAud(r.m2)}</td>
                        <td className="num">{fmtAud(r.m3)}</td>
                        <td className="num">{fmtAud(r.older)}</td>
                        <td className="num" style={{ fontWeight: 800, color: parseFloat(r.total) < 0 ? "var(--xui-red)" : undefined }}>
                          {fmtAud(r.total)}
                        </td>
                      </tr>
                      {expandedContact[r.contactId] &&
                        r.items.map((it, idx) => (
                          <tr key={`${r.contactId}-${idx}`} style={{ background: "#fafbfd", fontSize: 12.5 }}>
                            <td style={{ paddingLeft: 28 }}>
                              {it.invoiceNumber} ({it.invoiceType}) — Issue {it.issueDate} / Due {it.dueDate}
                            </td>
                            <td colSpan={6}>Bucket: {it.bucket}</td>
                            <td className="num">{fmtAud(it.outstanding)}</td>
                          </tr>
                        ))}
                    </Fragment>
                  ))}
                  <tr style={{ fontWeight: 800, background: "#eef5ff" }}>
                    <td>Total</td>
                    <td className="num">{fmtAud(aged.totals.current)}</td>
                    <td className="num">{fmtAud(aged.totals.lt1m)}</td>
                    <td className="num">{fmtAud(aged.totals.m1)}</td>
                    <td className="num">{fmtAud(aged.totals.m2)}</td>
                    <td className="num">{fmtAud(aged.totals.m3)}</td>
                    <td className="num">{fmtAud(aged.totals.older)}</td>
                    <td className="num">{fmtAud(aged.totals.total)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </main>
      </>
    );
  }

  // === SHORT-TERM CASH FLOW ===
  if (route === "cash-flow") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Reports &gt; Short-term Cash Flow</div>
            <h1 className="x-page-title">
              <BarChart3 size={20} color="var(--xui-nav-blue)" /> Short-Term Cash Flow Projection
            </h1>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                className={`x-btn ${cfDays === d ? "x-btn-primary" : ""}`}
                onClick={async () => {
                  setCfDays(d);
                  setCashFlow(await api.get<CashFlowData>(`/orgs/${orgId}/analytics/cash-flow?days=${d}`));
                }}
              >
                Next {d} days
              </button>
            ))}
          </div>
        </div>
        <main className="x-main">
          {cashFlow && (
            <>
              <div className="x-grid-4" style={{ marginBottom: 16 }}>
                <div className="x-card">
                  <div className="x-card-body">
                    <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Starting Bank Cash</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{fmtAud(cashFlow.currentCash)}</div>
                  </div>
                </div>
                <div className="x-card">
                  <div className="x-card-body">
                    <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Expected Inflows (AR)</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: "var(--xui-green)" }}>{fmtAud(cashFlow.expectedInflows)}</div>
                  </div>
                </div>
                <div className="x-card">
                  <div className="x-card-body">
                    <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Expected Outflows (AP)</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: "var(--xui-red)" }}>{fmtAud(cashFlow.expectedOutflows)}</div>
                  </div>
                </div>
                <div className="x-card">
                  <div className="x-card-body">
                    <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Projected Closing Cash ({cashFlow.days}d)</div>
                    <div style={{ fontSize: 22, fontWeight: 700 }}>{fmtAud(cashFlow.projectedEndBalance)}</div>
                  </div>
                </div>
              </div>
              <div className="x-card">
                <div className="x-card-header"><div className="x-card-title">Upcoming Invoices & Bills Due</div></div>
                <table className="x-table">
                  <thead>
                    <tr>
                      <th>Due Date</th>
                      <th>Document</th>
                      <th>Contact</th>
                      <th>Direction</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cashFlow.upcomingTransactions.map((u) => (
                      <tr key={u.invoiceId}>
                        <td>
                          {u.dueDate} {u.isOverdue && <span className="x-badge red">Overdue</span>}
                        </td>
                        <td style={{ fontWeight: 600 }}>{u.invoiceNumber}</td>
                        <td>{u.contactName}</td>
                        <td>
                          <span className={`x-badge ${u.direction === "INFLOW" ? "green" : "amber"}`}>{u.direction}</span>
                        </td>
                        <td className="num">{fmtAud(u.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </main>
      </>
    );
  }

  // === AU SIMPLER BAS ACTIVITY STATEMENT ===
  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Accounting &gt; Reports &gt; Activity Statement (ATO Simpler BAS)</div>
          <h1 className="x-page-title">
            Australian Simpler BAS Statement{" "}
            {bas && (
              <span className={`x-badge ${bas.status === "FINALISED" ? "green" : "blue"}`}>
                {bas.status === "FINALISED" ? <><Lock size={11} /> FINALISED</> : "DRAFT"}
              </span>
            )}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {bas && bas.status === "DRAFT" && canWrite && (
            <button className="x-btn x-btn-green" onClick={finaliseBas}>
              <CheckCircle2 size={15} /> Finalise BAS Statement
            </button>
          )}
        </div>
      </div>

      <main className="x-main">
        <div className="x-card" style={{ marginBottom: 16 }}>
          <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="x-field">
              <label>Quarter Preset</label>
              <select
                className="x-select"
                value={`${basFrom}|${basTo}`}
                onChange={(e) => {
                  const [f, t] = e.target.value.split("|");
                  if (f && t) {
                    setBasFrom(f);
                    setBasTo(t);
                  }
                }}
              >
                <option value="2026-07-01|2026-09-30">Q1 FY27 (Jul–Sep 2026)</option>
                <option value="2026-10-01|2026-12-31">Q2 FY27 (Oct–Dec 2026)</option>
                <option value="2027-01-01|2027-03-31">Q3 FY27 (Jan–Mar 2027)</option>
                <option value="2027-04-01|2027-06-30">Q4 FY27 (Apr–Jun 2027)</option>
              </select>
            </div>
            <div className="x-field">
              <label>From</label>
              <input type="date" className="x-input" value={basFrom} onChange={(e) => setBasFrom(e.target.value)} />
            </div>
            <div className="x-field">
              <label>To</label>
              <input type="date" className="x-input" value={basTo} onChange={(e) => setBasTo(e.target.value)} />
            </div>
            <button className="x-btn x-btn-primary" onClick={runReport}>
              <RefreshCw size={14} /> Refresh BAS
            </button>
            {bas && (
              <div style={{ fontSize: 12.5, color: "var(--xui-ink-muted)", paddingBottom: 6 }}>
                Basis: <strong>{bas.accountingMethod}</strong> • G1 Mode: <strong>{bas.g1Mode}</strong> • Journals:{" "}
                <strong>{bas.minJournalNumber ?? "-"} .. {bas.maxJournalNumber ?? "-"}</strong>
              </div>
            )}
          </div>
        </div>

        {bas && bas.unfiledIncludedCount > 0 && (
          <div className="x-alert warn">
            <AlertCircle size={17} />
            <div>
              <strong>Unfiled amounts from earlier periods included ({bas.unfiledIncludedCount} transactions):</strong>{" "}
              Transactions dated before <code>{bas.periodStart}</code> posted with Journal # &gt;{" "}
              <code>{bas.previousWatermark}</code> have been automatically captured so no GST is missed after prior BAS finalisation.
            </div>
          </div>
        )}

        {bas && (
          <>
            <div className="x-grid-4" style={{ marginBottom: 16 }}>
              <div className="x-card">
                <div className="x-card-body">
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>G1 Total Sales (Whole AUD)</div>
                  <div style={{ fontSize: 24, fontWeight: 800 }}>${Number(bas.labels.G1).toLocaleString()}</div>
                </div>
              </div>
              <div className="x-card">
                <div className="x-card-body">
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>1A GST on Sales</div>
                  <div style={{ fontSize: 24, fontWeight: 800 }}>${Number(bas.labels["1A"]).toLocaleString()}</div>
                </div>
              </div>
              <div className="x-card">
                <div className="x-card-body">
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>1B GST on Purchases</div>
                  <div style={{ fontSize: 24, fontWeight: 800 }}>${Number(bas.labels["1B"]).toLocaleString()}</div>
                </div>
              </div>
              <div className="x-card">
                <div className="x-card-body">
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>
                    Label 9 ({Number(bas.labels.Payment9) >= 0 ? "Payment to ATO" : "Refund from ATO"})
                  </div>
                  <div
                    style={{
                      fontSize: 24,
                      fontWeight: 800,
                      color: Number(bas.labels.Payment9) >= 0 ? "var(--xui-ink)" : "var(--xui-green)",
                    }}
                  >
                    ${Number(bas.labels.Payment9).toLocaleString()}
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)", marginTop: 4 }}>
                    G10 Cap: ${bas.labels.G10} • G11 Non-cap: ${bas.labels.G11}
                  </div>
                </div>
              </div>
            </div>

            <div className="x-grid-2" style={{ marginBottom: 16 }}>
              <div className="x-card">
                <div className="x-card-header"><div className="x-card-title">Transactions by Tax Rate</div></div>
                <table className="x-table">
                  <thead>
                    <tr>
                      <th>Tax Rate</th>
                      <th>Count</th>
                      <th className="num">Net AUD</th>
                      <th className="num">GST AUD</th>
                      <th className="num">Gross AUD</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bas.byTaxRate.map((b) => (
                      <tr key={b.taxCode}>
                        <td>{b.taxName}</td>
                        <td>{b.count}</td>
                        <td className="num">{fmtAud(b.netAmount)}</td>
                        <td className="num">{fmtAud(b.taxAmount)}</td>
                        <td className="num">{fmtAud(b.grossAmount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="x-card">
                <div className="x-card-header"><div className="x-card-title">Finalised Activity Statements</div></div>
                <table className="x-table">
                  <thead>
                    <tr>
                      <th>Period</th>
                      <th>Basis</th>
                      <th>Watermark J#</th>
                      <th className="num">Label 9</th>
                    </tr>
                  </thead>
                  <tbody>
                    {basHistory.map((h) => (
                      <tr key={h.id}>
                        <td>{h.period_start} .. {h.period_end}</td>
                        <td>{h.accounting_method}</td>
                        <td>#{h.max_journal_number ?? "-"}</td>
                        <td className="num" style={{ fontWeight: 700 }}>${h.net_payment_9_dollars}</td>
                      </tr>
                    ))}
                    {basHistory.length === 0 && (
                      <tr><td colSpan={4} style={{ color: "var(--xui-ink-muted)", textAlign: "center" }}>No finalised BAS lodgements yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">GST Audit Report ({bas.transactions.length} lines)</div>
              </div>
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Jnl #</th>
                    <th>Source</th>
                    <th>Description</th>
                    <th>Tax Rate</th>
                    <th className="num">Net</th>
                    <th className="num">GST</th>
                    <th className="num">Gross</th>
                  </tr>
                </thead>
                <tbody>
                  {bas.transactions.map((t, i) => (
                    <tr key={i} style={t.isUnfiledPriorPeriod ? { background: "var(--xui-amber-soft)" } : undefined}>
                      <td>
                        {t.date} {t.isUnfiledPriorPeriod && <span className="x-badge amber">Unfiled</span>}
                      </td>
                      <td>{t.journalNumber ? `#${t.journalNumber}` : "-"}</td>
                      <td>{t.sourceType}</td>
                      <td>{t.description || t.reference || "-"}</td>
                      <td>{t.taxName}</td>
                      <td className="num">{fmtAud(t.netAmount)}</td>
                      <td className="num">{fmtAud(t.taxAmount)}</td>
                      <td className="num">{fmtAud(t.grossAmount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </>
  );
}
