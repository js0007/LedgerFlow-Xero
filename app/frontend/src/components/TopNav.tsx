import React, { useEffect, useRef, useState } from "react";
import {
  Building2,
  ChevronDown,
  Plus,
  RefreshCw,
  Shield,
  Settings,
} from "lucide-react";
import type { OrgSummary, UserRole } from "../types";

export type RouteKey =
  | "dashboard"
  | "sales-overview"
  | "invoices"
  | "quotes"
  | "products"
  | "purchases-overview"
  | "bills"
  | "purchase-orders"
  | "expenses"
  | "contacts"
  | "bank-accounts"
  | "bank-reconcile"
  | "cash-coding"
  | "bank-rules"
  | "coa"
  | "manual-journals"
  | "find-recode"
  | "conversion-balances"
  | "assurance"
  | "audit-history"
  | "reports-hub"
  | "profit-and-loss"
  | "balance-sheet"
  | "trial-balance"
  | "journal-report"
  | "account-transactions"
  | "aged-receivables"
  | "aged-payables"
  | "cash-flow"
  | "simpler-bas"
  | "payroll"
  | "fixed-assets"
  | "projects"
  | "app-store"
  | "settings";

interface Props {
  orgs: OrgSummary[];
  activeOrg: OrgSummary;
  route: RouteKey;
  onNavigate: (r: RouteKey, extra?: any) => void;
  onSelectOrg: (orgId: string) => void;
  onCreateOrg: (name: string, abn: string) => Promise<void>;
  onResetDemo: () => Promise<void>;
  onSwitchRole: (role: UserRole) => Promise<void>;
  onQuickCreate: (kind: "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "QUOTE" | "PO" | "MJ" | "CONTACT") => void;
}

export const TopNav: React.FC<Props> = ({
  orgs,
  activeOrg,
  route,
  onNavigate,
  onSelectOrg,
  onCreateOrg,
  onResetDemo,
  onSwitchRole,
  onQuickCreate,
}) => {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [showNewOrg, setShowNewOrg] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgAbn, setNewOrgAbn] = useState("");
  const [busy, setBusy] = useState(false);
  const navRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (navRef.current && !navRef.current.contains(e.target as Node)) {
        setOpenMenu(null);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      const k = e.key.toLowerCase();
      if (k === "i") { e.preventDefault(); onQuickCreate("ACCREC"); }
      else if (k === "b") { e.preventDefault(); onQuickCreate("ACCPAY"); }
      else if (k === "c") { e.preventDefault(); onQuickCreate("CONTACT"); }
      else if (k === "j") { e.preventDefault(); onQuickCreate("MJ"); }
      else if (k === "q") { e.preventDefault(); onQuickCreate("QUOTE"); }
      else if (k === "o") { e.preventDefault(); onQuickCreate("PO"); }
    };
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [onQuickCreate]);

  const go = (r: RouteKey) => {
    setOpenMenu(null);
    onNavigate(r);
  };

  const isGroupActive = (keys: RouteKey[]) => keys.includes(route);

  const roles: UserRole[] = ["ADVISER", "STANDARD", "READONLY"];
  const nextRole = roles[(roles.indexOf(activeOrg.role) + 1) % roles.length];

  return (
    <>
      <header className="x-topnav" ref={navRef}>
        <div className="x-nav-left">
          {/* Org Switcher Pill */}
          <div className="x-dropdown-wrap">
            <button
              className="x-org-pill"
              onClick={() => setOpenMenu(openMenu === "org" ? null : "org")}
              data-testid="org-switcher-btn"
            >
              <Building2 size={15} />
              <span>{activeOrg.displayName}</span>
              <span style={{ opacity: 0.75, fontSize: 11 }}>{activeOrg.shortCode}</span>
              <ChevronDown size={14} />
            </button>
            {openMenu === "org" && (
              <div className="x-dropdown-menu" style={{ minWidth: 290 }}>
                <div className="x-menu-section">Switch Organisation (AU)</div>
                {orgs.map((o) => (
                  <button
                    key={o.id}
                    className="x-menu-item"
                    onClick={() => {
                      setOpenMenu(null);
                      onSelectOrg(o.id);
                    }}
                    style={{ fontWeight: o.id === activeOrg.id ? 700 : 400 }}
                  >
                    <span>{o.displayName}</span>
                    <span className="x-badge blue">{o.shortCode}</span>
                  </button>
                ))}
                <div style={{ borderTop: "1px solid var(--xui-border)", margin: "6px 0" }} />
                <button
                  className="x-menu-item"
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await onResetDemo();
                      setOpenMenu(null);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <RefreshCw size={14} /> Reset Demo Company (AU)
                  </span>
                </button>
                <button
                  className="x-menu-item"
                  onClick={() => {
                    setOpenMenu(null);
                    setShowNewOrg(true);
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Plus size={14} /> Add new organisation
                  </span>
                </button>
                <button className="x-menu-item" onClick={() => go("settings")}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <Settings size={14} /> Organisation &amp; Financial Settings
                  </span>
                </button>
              </div>
            )}
          </div>

          {/* Dashboard */}
          <button
            className={`x-nav-btn ${route === "dashboard" ? "active" : ""}`}
            onClick={() => go("dashboard")}
          >
            Dashboard
          </button>

          {/* Business */}
          <div className="x-dropdown-wrap">
            <button
              className={`x-nav-btn ${isGroupActive(["sales-overview", "invoices", "quotes", "products", "purchases-overview", "bills", "purchase-orders", "expenses", "contacts"]) ? "active" : ""}`}
              onClick={() => setOpenMenu(openMenu === "business" ? null : "business")}
            >
              Business <ChevronDown size={13} />
            </button>
            {openMenu === "business" && (
              <div className="x-dropdown-menu">
                <div className="x-menu-section">Sales</div>
                <button className="x-menu-item" onClick={() => go("sales-overview")}>Sales overview</button>
                <button className="x-menu-item" onClick={() => go("invoices")}>Invoices &amp; Credit notes</button>
                <button className="x-menu-item" onClick={() => go("quotes")}>Quotes</button>
                <button className="x-menu-item" onClick={() => go("products")}>Products &amp; services</button>
                <div className="x-menu-section">Purchases</div>
                <button className="x-menu-item" onClick={() => go("purchases-overview")}>Purchases overview</button>
                <button className="x-menu-item" onClick={() => go("bills")}>Bills to pay &amp; Supplier CN</button>
                <button className="x-menu-item" onClick={() => go("purchase-orders")}>Purchase orders</button>
                <button className="x-menu-item" onClick={() => go("expenses")}>Expenses</button>
                <div className="x-menu-section">Contacts</div>
                <button className="x-menu-item" onClick={() => go("contacts")}>All contacts (Customers / Suppliers)</button>
              </div>
            )}
          </div>

          {/* Accounting */}
          <div className="x-dropdown-wrap">
            <button
              className={`x-nav-btn ${isGroupActive(["bank-accounts", "bank-reconcile", "cash-coding", "bank-rules", "coa", "manual-journals", "find-recode", "conversion-balances", "assurance", "audit-history"]) ? "active" : ""}`}
              onClick={() => setOpenMenu(openMenu === "accounting" ? null : "accounting")}
            >
              Accounting <ChevronDown size={13} />
            </button>
            {openMenu === "accounting" && (
              <div className="x-dropdown-menu" style={{ minWidth: 260 }}>
                <div className="x-menu-section">Banking</div>
                <button className="x-menu-item" onClick={() => go("bank-accounts")}>Bank accounts &amp; Reconciliation</button>
                <button className="x-menu-item" onClick={() => go("cash-coding")}>Cash coding</button>
                <button className="x-menu-item" onClick={() => go("bank-rules")}>Bank rules</button>
                <div className="x-menu-section">General Ledger &amp; Controls</div>
                <button className="x-menu-item" onClick={() => go("coa")}>Chart of accounts (54 AU)</button>
                <button className="x-menu-item" onClick={() => go("manual-journals")}>Manual journals</button>
                <button className="x-menu-item" onClick={() => go("find-recode")}>Find and recode</button>
                <button className="x-menu-item" onClick={() => go("conversion-balances")}>Conversion balances</button>
                <button className="x-menu-item" onClick={() => go("assurance")}>Assurance dashboard</button>
                <button className="x-menu-item" onClick={() => go("audit-history")}>History &amp; notes (Audit log)</button>
              </div>
            )}
          </div>

          {/* Reporting & Tax */}
          <div className="x-dropdown-wrap">
            <button
              className={`x-nav-btn ${isGroupActive(["reports-hub", "profit-and-loss", "balance-sheet", "trial-balance", "journal-report", "account-transactions", "aged-receivables", "aged-payables", "cash-flow", "simpler-bas"]) ? "active" : ""}`}
              onClick={() => setOpenMenu(openMenu === "reports" ? null : "reports")}
            >
              Reporting &amp; BAS <ChevronDown size={13} />
            </button>
            {openMenu === "reports" && (
              <div className="x-dropdown-menu" style={{ minWidth: 265 }}>
                <button className="x-menu-item" onClick={() => go("reports-hub")} style={{ fontWeight: 700 }}>All Reports Hub</button>
                <div className="x-menu-section">Tax (AU ATO)</div>
                <button className="x-menu-item" onClick={() => go("simpler-bas")}>
                  <span>Activity Statements (Simpler BAS)</span>
                  <span className="x-badge green">AU</span>
                </button>
                <div className="x-menu-section">Financial Statements</div>
                <button className="x-menu-item" onClick={() => go("profit-and-loss")}>Profit &amp; Loss (Accrual / Cash)</button>
                <button className="x-menu-item" onClick={() => go("balance-sheet")}>Balance Sheet</button>
                <button className="x-menu-item" onClick={() => go("trial-balance")}>Trial Balance</button>
                <button className="x-menu-item" onClick={() => go("cash-flow")}>Short-term Cash Flow</button>
                <div className="x-menu-section">Ledgers &amp; Aging</div>
                <button className="x-menu-item" onClick={() => go("aged-receivables")}>Aged Receivables Summary</button>
                <button className="x-menu-item" onClick={() => go("aged-payables")}>Aged Payables Summary</button>
                <button className="x-menu-item" onClick={() => go("journal-report")}>Journal Report</button>
                <button className="x-menu-item" onClick={() => go("account-transactions")}>Account Transactions</button>
              </div>
            )}
          </div>

          {/* Operations & P2 Add-ons */}
          <div className="x-dropdown-wrap">
            <button
              className={`x-nav-btn ${isGroupActive(["payroll", "fixed-assets", "projects", "app-store"]) ? "active" : ""}`}
              onClick={() => setOpenMenu(openMenu === "modules" ? null : "modules")}
            >
              Payroll &amp; More <ChevronDown size={13} />
            </button>
            {openMenu === "modules" && (
              <div className="x-dropdown-menu">
                <div className="x-menu-section">AU Operational Modules</div>
                <button className="x-menu-item" onClick={() => go("payroll")}>Payroll (AU / STP / Super)</button>
                <button className="x-menu-item" onClick={() => go("fixed-assets")}>Fixed Assets Register</button>
                <button className="x-menu-item" onClick={() => go("projects")}>Projects &amp; Time Tracking</button>
                <div className="x-menu-section">Ecosystem</div>
                <button className="x-menu-item" onClick={() => go("app-store")}>Connected Apps &amp; App Store</button>
              </div>
            )}
          </div>

          <button className={`x-nav-btn ${route === "settings" ? "active" : ""}`} onClick={() => go("settings")}>
            Settings
          </button>
        </div>

        {/* Right Controls: + Create new, Role Switcher */}
        <div className="x-nav-right">
          <div className="x-dropdown-wrap">
            <button
              className="x-icon-circle"
              title="Create new (Alt+I, Alt+B, Alt+J...)"
              onClick={() => setOpenMenu(openMenu === "create" ? null : "create")}
              data-testid="quick-create-btn"
            >
              <Plus size={18} />
            </button>
            {openMenu === "create" && (
              <div className="x-dropdown-menu right" style={{ minWidth: 240 }}>
                <div className="x-menu-section">Create New</div>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("ACCREC"); }}>
                  <span>Sales Invoice</span><span className="x-kbd">Alt+I</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("ACCPAY"); }}>
                  <span>Bill</span><span className="x-kbd">Alt+B</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("ACCRECCREDIT"); }}>
                  <span>Sales Credit Note</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("QUOTE"); }}>
                  <span>Quote</span><span className="x-kbd">Alt+Q</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("PO"); }}>
                  <span>Purchase Order</span><span className="x-kbd">Alt+O</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("MJ"); }}>
                  <span>Manual Journal</span><span className="x-kbd">Alt+J</span>
                </button>
                <button className="x-menu-item" onClick={() => { setOpenMenu(null); onQuickCreate("CONTACT"); }}>
                  <span>Contact</span><span className="x-kbd">Alt+C</span>
                </button>
              </div>
            )}
          </div>

          <button
            className="x-role-badge"
            title={`Current role: ${activeOrg.role}. Click to cycle role (Adviser → Standard → ReadOnly)`}
            onClick={() => onSwitchRole(nextRole)}
            data-testid="role-switcher-btn"
          >
            <Shield size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
            Role: {activeOrg.role}
          </button>
        </div>
      </header>

      {showNewOrg && (
        <div className="x-modal-backdrop" onClick={() => setShowNewOrg(false)}>
          <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
            <div className="x-modal-head">
              <strong>Add New AU Organisation (54 COA + 11 TaxRates)</strong>
              <button className="x-btn x-btn-sm" onClick={() => setShowNewOrg(false)}>Close</button>
            </div>
            <div className="x-modal-body" style={{ display: "grid", gap: 12 }}>
              <div className="x-field">
                <label>Organisation Name</label>
                <input
                  className="x-input"
                  value={newOrgName}
                  onChange={(e) => setNewOrgName(e.target.value)}
                  placeholder="e.g. Melbourne Advisory Pty Ltd"
                />
              </div>
              <div className="x-field">
                <label>Australian Business Number (ABN)</label>
                <input
                  className="x-input"
                  value={newOrgAbn}
                  onChange={(e) => setNewOrgAbn(e.target.value)}
                  placeholder="12 345 678 901"
                />
              </div>
            </div>
            <div className="x-modal-foot">
              <button className="x-btn" onClick={() => setShowNewOrg(false)}>Cancel</button>
              <button
                className="x-btn x-btn-primary"
                disabled={busy || !newOrgName.trim()}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await onCreateOrg(newOrgName.trim(), newOrgAbn.trim());
                    setNewOrgName("");
                    setNewOrgAbn("");
                    setShowNewOrg(false);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Create AU Organisation
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
