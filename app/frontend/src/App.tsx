import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AccountingWorkspaceView } from "./components/AccountingWorkspaceView";
import { BankingReconcileView } from "./components/BankingReconcileView";
import { CommercialViews } from "./components/CommercialViews";
import { ContactsAndSettingsView } from "./components/ContactsAndSettingsView";
import { DashboardView } from "./components/DashboardView";
import { ReportsAndBasView } from "./components/ReportsAndBasView";
import { type RouteKey, TopNav } from "./components/TopNav";
import type {
  AccountItem,
  AuthMeResponse,
  BankAccountSummary,
  ContactItem,
  DashboardData,
  OrgSummary,
  ProductItem,
  TaxRateItem,
  TrackingCategory,
  UserRole,
} from "./types";

interface ToastMsg {
  id: number;
  kind: "success" | "error" | "info";
  msg: string;
}

export function App() {
  const [orgs, setOrgs] = useState<OrgSummary[]>([]);
  const [activeOrgId, setActiveOrgId] = useState<string>("");
  const [route, setRoute] = useState<RouteKey>("dashboard");
  const [selectedBankId, setSelectedBankId] = useState<string>("");
  const [externalCreateKind, setExternalCreateKind] = useState<
    "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "QUOTE" | "PO" | null
  >(null);

  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [taxRates, setTaxRates] = useState<TaxRateItem[]>([]);
  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [banks, setBanks] = useState<BankAccountSummary[]>([]);
  const [tracking, setTracking] = useState<TrackingCategory[]>([]);
  const [toasts, setToasts] = useState<ToastMsg[]>([]);

  const pushToast = useCallback((kind: "success" | "error" | "info", msg: string) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev, { id, kind, msg }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5200);
  }, []);

  const loadBootstrap = useCallback(async (preferOrgId?: string) => {
    const me = await api.get<AuthMeResponse>("/auth/me");
    setOrgs(me.organisations);
    setActiveOrgId((prev) => {
      if (preferOrgId && me.organisations.some((o) => o.id === preferOrgId)) return preferOrgId;
      if (prev && me.organisations.some((o) => o.id === prev)) return prev;
      const demo = me.organisations.find((o) => o.shortCode === "!VD61z");
      return demo?.id || me.organisations[0]?.id || "";
    });
  }, []);

  const loadOrgContext = useCallback(async (orgId: string) => {
    if (!orgId) return;
    const [dash, accs, trs, cts, prods, bks, tks] = await Promise.all([
      api.get<DashboardData>(`/orgs/${orgId}/dashboard`),
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts`),
      api.get<TaxRateItem[]>(`/orgs/${orgId}/tax-rates`),
      api.get<ContactItem[]>(`/orgs/${orgId}/contacts`),
      api.get<ProductItem[]>(`/orgs/${orgId}/products`),
      api.get<BankAccountSummary[]>(`/orgs/${orgId}/bank-accounts`),
      api.get<TrackingCategory[]>(`/orgs/${orgId}/tracking-categories`),
    ]);
    setDashboard(dash);
    setAccounts(accs);
    setTaxRates(trs);
    setContacts(cts);
    setProducts(prods);
    setBanks(bks);
    setTracking(tks);
    setSelectedBankId((prev) => (bks.some((b) => b.id === prev) ? prev : bks[0]?.id || ""));
  }, []);

  useEffect(() => {
    loadBootstrap().catch((e: Error) => pushToast("error", e.message));
  }, [loadBootstrap, pushToast]);

  useEffect(() => {
    if (activeOrgId) {
      loadOrgContext(activeOrgId).catch((e: Error) => pushToast("error", e.message));
    }
  }, [activeOrgId, loadOrgContext, pushToast]);

  const activeOrg = orgs.find((o) => o.id === activeOrgId) || orgs[0] || null;

  function handleNavigate(nextRoute: RouteKey, extra?: { bankAccountId?: string }) {
    if (extra?.bankAccountId) {
      setSelectedBankId(extra.bankAccountId);
    }
    setRoute(nextRoute);
  }

  async function handleCreateOrg(name: string, abn: string) {
    try {
      const created = await api.post<OrgSummary>("/orgs", { displayName: name, abn: abn || null });
      await loadBootstrap(created.id);
      setRoute("dashboard");
      pushToast("success", `Created AU organisation '${created.displayName}' (${created.shortCode}).`);
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  async function handleResetDemo() {
    try {
      const demo = await api.post<OrgSummary>("/orgs/demo/reset");
      await loadBootstrap(demo.id);
      await loadOrgContext(demo.id);
      setRoute("dashboard");
      pushToast("success", "Demo Company (AU) !VD61z reset to pristine golden state.");
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  async function handleSwitchRole(newRole: UserRole) {
    if (!activeOrg) return;
    try {
      await api.post("/auth/switch-role", { orgId: activeOrg.id, role: newRole });
      await loadBootstrap(activeOrg.id);
      pushToast("info", `Switched active permission role to ${newRole}.`);
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  function handleQuickCreate(kind: "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "QUOTE" | "PO" | "MJ" | "CONTACT") {
    if (kind === "MJ") {
      setRoute("manual-journals");
      return;
    }
    if (kind === "CONTACT") {
      setRoute("contacts");
      return;
    }
    setExternalCreateKind(kind);
    if (kind === "ACCREC" || kind === "ACCRECCREDIT") setRoute("invoices");
    else if (kind === "QUOTE") setRoute("quotes");
    else if (kind === "ACCPAY") setRoute("bills");
    else if (kind === "PO") setRoute("purchase-orders");
  }

  if (!activeOrg) {
    return (
      <div style={{ padding: 48, textAlign: "center", fontFamily: "sans-serif" }}>
        <h2>Loading LedgerFlow AU...</h2>
      </div>
    );
  }

  const isCommercial =
    route === "sales-overview" ||
    route === "invoices" ||
    route === "quotes" ||
    route === "purchases-overview" ||
    route === "bills" ||
    route === "purchase-orders";

  const isBanking =
    route === "bank-accounts" || route === "bank-reconcile" || route === "cash-coding" || route === "bank-rules";

  const isAccounting =
    route === "coa" ||
    route === "manual-journals" ||
    route === "find-recode" ||
    route === "conversion-balances" ||
    route === "assurance" ||
    route === "audit-history";

  const isReporting =
    route === "reports-hub" ||
    route === "profit-and-loss" ||
    route === "balance-sheet" ||
    route === "trial-balance" ||
    route === "journal-report" ||
    route === "account-transactions" ||
    route === "aged-receivables" ||
    route === "aged-payables" ||
    route === "cash-flow" ||
    route === "simpler-bas";

  return (
    <div>
      <TopNav
        orgs={orgs}
        activeOrg={activeOrg}
        route={route}
        onNavigate={handleNavigate}
        onSelectOrg={(id) => {
          setActiveOrgId(id);
          setRoute("dashboard");
        }}
        onCreateOrg={handleCreateOrg}
        onResetDemo={handleResetDemo}
        onSwitchRole={handleSwitchRole}
        onQuickCreate={handleQuickCreate}
      />

      {route === "dashboard" && (
        <DashboardView
          org={activeOrg}
          data={dashboard}
          onNavigate={handleNavigate}
          onOpenImport={(bankId) => {
            setSelectedBankId(bankId);
            setRoute("bank-reconcile");
          }}
          onQuickCreate={(k) => handleQuickCreate(k)}
          onSwitchToDemo={() => {
            const demo = orgs.find((o) => o.shortCode === "!VD61z");
            if (demo) setActiveOrgId(demo.id);
          }}
        />
      )}

      {isCommercial && (
        <CommercialViews
          org={activeOrg}
          mode={route}
          accounts={accounts}
          taxRates={taxRates}
          contacts={contacts}
          products={products}
          banks={banks}
          tracking={tracking}
          externalCreateKind={externalCreateKind}
          onClearExternalCreate={() => setExternalCreateKind(null)}
          onNotify={pushToast}
          onNavigate={handleNavigate}
          onDataChanged={async () => {
            await loadOrgContext(activeOrg.id);
          }}
        />
      )}

      {isBanking && (
        <BankingReconcileView
          orgId={activeOrg.id}
          route={route}
          role={activeOrg.role}
          selectedBankId={selectedBankId}
          onSelectBankId={setSelectedBankId}
          onNavigate={handleNavigate}
          onToast={pushToast}
        />
      )}

      {isAccounting && (
        <AccountingWorkspaceView
          orgId={activeOrg.id}
          route={route}
          role={activeOrg.role}
          onToast={pushToast}
        />
      )}

      {isReporting && (
        <ReportsAndBasView
          orgId={activeOrg.id}
          route={route}
          role={activeOrg.role}
          onNavigate={handleNavigate}
          onToast={pushToast}
        />
      )}

      {!isCommercial && !isBanking && !isAccounting && !isReporting && route !== "dashboard" && (
        <ContactsAndSettingsView
          orgId={activeOrg.id}
          route={route}
          role={activeOrg.role}
          onNavigate={handleNavigate}
          onOrgUpdated={() => loadBootstrap(activeOrg.id)}
          onToast={pushToast}
        />
      )}

      <div className="x-toast-stack" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`x-toast ${t.kind === "error" ? "error" : t.kind === "success" ? "success" : ""}`}>
            <span>{t.msg}</span>
            <button
              style={{
                background: "transparent",
                border: "none",
                color: "#fff",
                cursor: "pointer",
                fontWeight: 700,
              }}
              onClick={() => setToasts((p) => p.filter((x) => x.id !== t.id))}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
export default App;
