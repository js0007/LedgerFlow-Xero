import React from "react";
import { ArrowRight, CheckCircle2, FileText, Landmark, Plus, Receipt, Upload } from "lucide-react";
import { fmtAud, fmtAudSigned } from "../api";
import type { DashboardData, OrgSummary } from "../types";
import type { RouteKey } from "./TopNav";

interface Props {
  org: OrgSummary;
  data: DashboardData | null;
  onNavigate: (r: RouteKey, extra?: any) => void;
  onOpenImport: (bankAccountId: string) => void;
  onQuickCreate: (kind: "ACCREC" | "ACCPAY" | "MJ" | "CONTACT") => void;
  onSwitchToDemo: () => void;
}

export const DashboardView: React.FC<Props> = ({
  org,
  data,
  onNavigate,
  onOpenImport,
  onQuickCreate,
  onSwitchToDemo,
}) => {
  if (!data) {
    return (
      <div className="x-main">
        <div className="x-card"><div className="x-card-body">Loading organisation financial overview...</div></div>
      </div>
    );
  }

  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Home &bull; {org.shortCode} &bull; AUD (Australia / ATO Simpler BAS)</div>
          <h1 className="x-page-title">
            {org.displayName}
            {org.shortCode === "!VD61z" ? (
              <span className="x-badge green">Demo Sandbox Live</span>
            ) : (
              <span className="x-badge blue">Clean AU Ledger</span>
            )}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {org.shortCode !== "!VD61z" && (
            <button className="x-btn" onClick={onSwitchToDemo}>
              Open Demo Company (!VD61z)
            </button>
          )}
          <button className="x-btn" onClick={() => onQuickCreate("ACCPAY")}>
            <Receipt size={14} /> New Bill
          </button>
          <button className="x-btn x-btn-primary" onClick={() => onQuickCreate("ACCREC")}>
            <Plus size={14} /> New Invoice
          </button>
        </div>
      </div>

      <div className="x-main">
        {data.bankAccounts.length === 0 && (
          <div className="x-alert info">
            <Landmark size={18} />
            <div style={{ flex: 1 }}>
              <strong>Welcome to your Clean AU Organisation ({org.shortCode})!</strong> Your 54 AU Chart of Accounts and 11 ATO Tax Rates are seeded and ready. Add a bank account or import a statement CSV to begin reconciling, or switch to <strong>Demo Company (AU)</strong> to explore live sample data.
            </div>
            <button className="x-btn x-btn-sm x-btn-primary" onClick={() => onNavigate("bank-accounts")}>
              Add Bank Account
            </button>
          </div>
        )}

        {/* Top Row: Bank Twin Balances + AR / AP Cards */}
        <div className="x-grid-2" style={{ marginBottom: 18 }}>
          {/* Bank Accounts Widget */}
          <div className="x-card">
            <div className="x-card-header">
              <h2 className="x-card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Landmark size={16} color="var(--xui-nav-blue)" /> Bank Accounts (Twin Balances)
              </h2>
              <button className="x-btn x-btn-sm" onClick={() => onNavigate("bank-accounts")}>
                Manage Accounts
              </button>
            </div>
            <div className="x-card-body">
              {data.bankAccounts.length === 0 ? (
                <div style={{ color: "var(--xui-ink-muted)", padding: "12px 0" }}>
                  No active bank accounts yet. Click <strong>Manage Accounts</strong> to create one.
                </div>
              ) : (
                data.bankAccounts.map((b) => {
                  const stmtNeg = Number(b.statementBalance) < 0;
                  const bookNeg = Number(b.bookBalance) < 0;
                  return (
                    <div
                      key={b.id}
                      style={{
                        padding: "12px 0",
                        borderBottom: "1px solid #eceff3",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 12,
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--xui-nav-blue)", cursor: "pointer" }}
                             onClick={() => onNavigate("bank-reconcile", { bankId: b.id })}>
                          {b.name}
                        </div>
                        <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>
                          {b.bankAccountNumber || "No BSB/Acct set"} &bull; {b.currency}
                        </div>
                        <div style={{ marginTop: 8, display: "flex", gap: 22 }}>
                          <div>
                            <div style={{ fontSize: 11, color: "var(--xui-ink-muted)" }}>Statement balance</div>
                            <div className="num" style={{ fontWeight: 700, fontSize: 15, color: stmtNeg ? "var(--xui-red)" : "var(--xui-ink)" }}>
                              ${fmtAudSigned(b.statementBalance)}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 11, color: "var(--xui-ink-muted)" }}>Balance in Xero</div>
                            <div className="num" style={{ fontWeight: 700, fontSize: 15, color: bookNeg ? "var(--xui-red)" : "var(--xui-ink)" }}>
                              ${fmtAudSigned(b.bookBalance)}
                              {bookNeg && <span className="x-badge amber" style={{ marginLeft: 6 }}>Overdraft</span>}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                        {b.unreconciledCount > 0 ? (
                          <button
                            className="x-btn x-btn-primary x-btn-sm"
                            onClick={() => onNavigate("bank-reconcile", { bankId: b.id })}
                          >
                            Reconcile {b.unreconciledCount} item{b.unreconciledCount > 1 ? "s" : ""}
                          </button>
                        ) : (
                          <span className="x-badge green">
                            <CheckCircle2 size={12} /> Reconciled
                          </span>
                        )}
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="x-btn x-btn-sm" onClick={() => onNavigate("cash-coding", { bankId: b.id })}>
                            Cash Coding
                          </button>
                          <button className="x-btn x-btn-sm" onClick={() => onOpenImport(b.id)}>
                            <Upload size={12} /> Import CSV
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* Right Column: AR + AP Cards */}
          <div style={{ display: "grid", gap: 16 }}>
            <div className="x-card">
              <div className="x-card-header">
                <h2 className="x-card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <FileText size={16} color="var(--xui-green)" /> Invoices owed to you
                </h2>
                <button className="x-btn x-btn-sm" onClick={() => onNavigate("invoices")}>View All</button>
              </div>
              <div className="x-card-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div style={{ padding: 12, background: "#f7fafc", borderRadius: 6, border: "1px solid #e3e9f1" }}>
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{data.receivables.awaitingCount} Awaiting payment</div>
                  <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                    ${fmtAud(data.receivables.awaitingAmount)}
                  </div>
                </div>
                <div style={{ padding: 12, background: Number(data.receivables.overdueAmount) > 0 ? "var(--xui-red-soft)" : "#f7fafc", borderRadius: 6, border: "1px solid #e3e9f1" }}>
                  <div style={{ fontSize: 12, color: Number(data.receivables.overdueAmount) > 0 ? "var(--xui-red)" : "var(--xui-ink-muted)" }}>
                    {data.receivables.overdueCount} Overdue
                  </div>
                  <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4, color: Number(data.receivables.overdueAmount) > 0 ? "var(--xui-red)" : "var(--xui-ink)" }}>
                    ${fmtAud(data.receivables.overdueAmount)}
                  </div>
                </div>
              </div>
            </div>

            <div className="x-card">
              <div className="x-card-header">
                <h2 className="x-card-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Receipt size={16} color="var(--xui-primary-cta)" /> Bills you need to pay
                </h2>
                <button className="x-btn x-btn-sm" onClick={() => onNavigate("bills")}>View All</button>
              </div>
              <div className="x-card-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div style={{ padding: 12, background: "#f7fafc", borderRadius: 6, border: "1px solid #e3e9f1" }}>
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{data.payables.awaitingCount} Awaiting payment</div>
                  <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                    ${fmtAud(data.payables.awaitingAmount)}
                  </div>
                </div>
                <div style={{ padding: 12, background: Number(data.payables.overdueAmount) > 0 ? "var(--xui-amber-soft)" : "#f7fafc", borderRadius: 6, border: "1px solid #e3e9f1" }}>
                  <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{data.payables.overdueCount} Overdue</div>
                  <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                    ${fmtAud(data.payables.overdueAmount)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Row: Account Watchlist + Recent Invoice Payments + Quick Compliance */}
        <div className="x-grid-3">
          <div className="x-card">
            <div className="x-card-header">
              <h2 className="x-card-title">Account Watchlist</h2>
              <button className="x-btn x-btn-sm" onClick={() => onNavigate("coa")}>COA</button>
            </div>
            <table className="x-table">
              <thead>
                <tr><th>Account</th><th className="num">YTD AUD</th></tr>
              </thead>
              <tbody>
                {data.watchlist.map((w) => (
                  <tr key={w.id} className="clickable" onClick={() => onNavigate("account-transactions", { accountId: w.id })}>
                    <td><strong>{w.code}</strong> &mdash; {w.name}</td>
                    <td className="num">${fmtAud(w.ytd)}</td>
                  </tr>
                ))}
                {data.watchlist.length === 0 && (
                  <tr><td colSpan={2} style={{ color: "var(--xui-ink-muted)" }}>No accounts pinned to watchlist.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="x-card">
            <div className="x-card-header">
              <h2 className="x-card-title">Recent Invoice Payments</h2>
              <button className="x-btn x-btn-sm" onClick={() => onNavigate("aged-receivables")}>Aged AR</button>
            </div>
            <table className="x-table">
              <thead>
                <tr><th>Invoice</th><th>Date</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {data.recentInvoicePayments.map((p, idx) => (
                  <tr key={idx}>
                    <td><strong>{p.invoiceNumber}</strong><div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>{p.contactName}</div></td>
                    <td>{p.date}</td>
                    <td className="num">${fmtAud(p.amount)}</td>
                  </tr>
                ))}
                {data.recentInvoicePayments.length === 0 && (
                  <tr><td colSpan={3} style={{ color: "var(--xui-ink-muted)" }}>No customer payments recorded yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="x-card">
            <div className="x-card-header">
              <h2 className="x-card-title">Quick Financial Workflows</h2>
            </div>
            <div className="x-card-body" style={{ display: "grid", gap: 8 }}>
              <button className="x-btn" style={{ justifyContent: "space-between" }} onClick={() => onNavigate("simpler-bas")}>
                <span>AU Simpler BAS Return (G1 / 1A / 1B / 9)</span>
                <ArrowRight size={14} />
              </button>
              <button className="x-btn" style={{ justifyContent: "space-between" }} onClick={() => onNavigate("profit-and-loss")}>
                <span>Profit &amp; Loss (Accrual &amp; Cash Basis)</span>
                <ArrowRight size={14} />
              </button>
              <button className="x-btn" style={{ justifyContent: "space-between" }} onClick={() => onNavigate("balance-sheet")}>
                <span>Balance Sheet &amp; Overdraft Classification</span>
                <ArrowRight size={14} />
              </button>
              <button className="x-btn" style={{ justifyContent: "space-between" }} onClick={() => onNavigate("manual-journals")}>
                <span>Manual Journals (47 Accounts / Auto-Reverse)</span>
                <ArrowRight size={14} />
              </button>
              <button className="x-btn" style={{ justifyContent: "space-between" }} onClick={() => onNavigate("find-recode")}>
                <span>Find &amp; Recode (Adviser Reclassification)</span>
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};
