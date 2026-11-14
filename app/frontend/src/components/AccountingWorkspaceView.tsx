import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, History, Lock, Plus, Search, ShieldCheck, Undo2 } from "lucide-react";
import { api, fmtAud } from "../api";
import type {
  AccountItem,
  ManualJournalDoc,
  TaxRateItem,
  TrackingCategory,
  UserRole,
} from "../types";
import type { RouteKey } from "./TopNav";

interface RecodeLine {
  journalLineId: string;
  journalId: string;
  journalNumber: number;
  date: string;
  sourceType: string;
  contactName: string | null;
  description: string | null;
  accountId: string;
  accountCode: string | null;
  accountName: string;
  taxRateId: string | null;
  taxName: string | null;
  debit: string;
  credit: string;
}

interface ConversionResponse {
  orgId: string;
  conversionDate: string;
  conversionLockedAt: string | null;
  entries: { accountId: string; code: string | null; name: string; accountType: string; debit: string; credit: string }[];
  totalDebit: string;
  totalCredit: string;
  historicalAdjustmentDiff: string;
}

interface AssuranceResponse {
  duplicateBankContacts: { bank_bsb_account: string; cnt: number; names: string }[];
  voidedDocuments: { id: string; type: string; number: string; date: string; total: string }[];
  manualBankLines: { id: string; tx_date: string; amount_cents: number; payee: string | null; description: string | null }[];
  userActivity: { actor_name: string; actions: number; last_active: string }[];
}

interface AuditLogRow {
  id: string;
  actor_name: string;
  entity_type: string;
  entity_id: string;
  action: string;
  summary: string;
  created_at: string;
}

interface Props {
  orgId: string;
  route: RouteKey;
  role: UserRole;
  onToast: (type: "success" | "error" | "info", msg: string) => void;
}

export function AccountingWorkspaceView({ orgId, route, role, onToast }: Props) {
  const canWrite = role !== "READONLY";
  const isAdviser = role === "ADVISER";

  const [allAccounts, setAllAccounts] = useState<AccountItem[]>([]);
  const [mjAccounts, setMjAccounts] = useState<AccountItem[]>([]);
  const [taxRates, setTaxRates] = useState<TaxRateItem[]>([]);
  const [tracking, setTracking] = useState<TrackingCategory[]>([]);

  // COA state
  const [coaFilterClass, setCoaFilterClass] = useState<string>("ALL");
  const [coaSearch, setCoaSearch] = useState("");
  const [showArchivedCoa, setShowArchivedCoa] = useState(false);
  const [accModalOpen, setAccModalOpen] = useState(false);
  const [editingAcc, setEditingAcc] = useState<AccountItem | null>(null);
  const [accForm, setAccForm] = useState({
    code: "",
    name: "",
    accountType: "EXPENSE",
    description: "",
    defaultTaxRateId: "",
    showOnWatchlist: false,
  });

  // Manual Journals state
  const [journals, setJournals] = useState<ManualJournalDoc[]>([]);
  const [mjTab, setMjTab] = useState<string>("ALL");
  const [mjModalOpen, setMjModalOpen] = useState(false);
  const [mjEditingId, setMjEditingId] = useState<string | null>(null);
  const [mjForm, setMjForm] = useState({
    narration: "",
    journalDate: new Date().toISOString().slice(0, 10),
    autoReversingDate: "",
    taxMode: "NO_TAX" as "NO_TAX" | "EXCLUSIVE" | "INCLUSIVE",
    showOnCashBasis: false,
    lines: [
      { description: "", accountId: "", taxRateId: "", debit: "0.00", credit: "0.00", tracking1OptionId: "" },
      { description: "", accountId: "", taxRateId: "", debit: "0.00", credit: "0.00", tracking1OptionId: "" },
    ],
  });

  // Find & Recode
  const [recodeFilterAcc, setRecodeFilterAcc] = useState("");
  const [recodeLines, setRecodeLines] = useState<RecodeLine[]>([]);
  const [recodeHistory, setRecodeHistory] = useState<Record<string, unknown>[]>([]);
  const [recodeSel, setRecodeSel] = useState<Record<string, boolean>>({});
  const [recodeTargetAcc, setRecodeTargetAcc] = useState("");
  const [recodeTargetTrack, setRecodeTargetTrack] = useState("");

  // Conversion Balances
  const [convData, setConvData] = useState<ConversionResponse | null>(null);
  const [convDate, setConvDate] = useState("2026-07-01");
  const [convAmounts, setConvAmounts] = useState<Record<string, { debit: string; credit: string }>>({});
  const [convLock, setConvLock] = useState(false);

  // Assurance & Audit
  const [assurance, setAssurance] = useState<AssuranceResponse | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogRow[]>([]);

  async function loadCore() {
    const [accs, mjaccs, trs, tks] = await Promise.all([
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts?includeArchived=true`),
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts?excludeManualExcluded=true`),
      api.get<TaxRateItem[]>(`/orgs/${orgId}/tax-rates`),
      api.get<TrackingCategory[]>(`/orgs/${orgId}/tracking-categories`),
    ]);
    setAllAccounts(accs);
    setMjAccounts(mjaccs);
    setTaxRates(trs);
    setTracking(tks);
  }

  async function loadRouteData() {
    if (route === "manual-journals") {
      setJournals(await api.get<ManualJournalDoc[]>(`/orgs/${orgId}/manual-journals`));
    } else if (route === "find-recode") {
      const qs = recodeFilterAcc ? `?accountId=${encodeURIComponent(recodeFilterAcc)}` : "";
      const res = await api.get<{ lines: RecodeLine[]; history: Record<string, unknown>[] }>(
        `/orgs/${orgId}/find-and-recode${qs}`
      );
      setRecodeLines(res.lines);
      setRecodeHistory(res.history);
    } else if (route === "conversion-balances") {
      const cb = await api.get<ConversionResponse>(`/orgs/${orgId}/conversion-balances`);
      setConvData(cb);
      setConvDate(cb.conversionDate || "2026-07-01");
      const map: Record<string, { debit: string; credit: string }> = {};
      for (const e of cb.entries) map[e.accountId] = { debit: e.debit, credit: e.credit };
      setConvAmounts(map);
    } else if (route === "assurance") {
      setAssurance(await api.get<AssuranceResponse>(`/orgs/${orgId}/assurance`));
    } else if (route === "audit-history") {
      setAuditLogs(await api.get<AuditLogRow[]>(`/orgs/${orgId}/audit-logs`));
    }
  }

  useEffect(() => {
    loadCore()
      .then(() => loadRouteData())
      .catch((e: Error) => onToast("error", e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, route]);

  const noTaxRate = taxRates.find((t) => t.code === "NONE") || taxRates[0];
  const track1 = tracking[0] || null;

  // --- COA HANDLERS ---
  async function saveAccount() {
    try {
      if (editingAcc) {
        await api.patch(`/orgs/${orgId}/accounts/${editingAcc.id}`, {
          name: accForm.name,
          description: accForm.description,
          defaultTaxRateId: accForm.defaultTaxRateId || null,
          showOnWatchlist: accForm.showOnWatchlist,
        });
        onToast("success", `Updated account ${editingAcc.code || ""} ${accForm.name}.`);
      } else {
        await api.post(`/orgs/${orgId}/accounts`, {
          code: accForm.code,
          name: accForm.name,
          accountType: accForm.accountType,
          description: accForm.description,
          defaultTaxRateId: accForm.defaultTaxRateId || null,
          showOnWatchlist: accForm.showOnWatchlist,
        });
        onToast("success", `Created account ${accForm.code} ${accForm.name}.`);
      }
      setAccModalOpen(false);
      await loadCore();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function archiveAccount(acc: AccountItem) {
    try {
      await api.del(`/orgs/${orgId}/accounts/${acc.id}`);
      onToast("success", `Archived account ${acc.code || ""} ${acc.name}.`);
      await loadCore();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // --- MANUAL JOURNAL HANDLERS ---
  function openNewMj() {
    setMjEditingId(null);
    const a1 = mjAccounts[0]?.id || "";
    const a2 = mjAccounts[1]?.id || a1;
    setMjForm({
      narration: "",
      journalDate: new Date().toISOString().slice(0, 10),
      autoReversingDate: "",
      taxMode: "NO_TAX",
      showOnCashBasis: false,
      lines: [
        { description: "", accountId: a1, taxRateId: noTaxRate?.id || "", debit: "0.00", credit: "0.00", tracking1OptionId: "" },
        { description: "", accountId: a2, taxRateId: noTaxRate?.id || "", debit: "0.00", credit: "0.00", tracking1OptionId: "" },
      ],
    });
    setMjModalOpen(true);
  }

  function openEditMj(j: ManualJournalDoc) {
    setMjEditingId(j.id);
    setMjForm({
      narration: j.narration,
      journalDate: j.journalDate,
      autoReversingDate: j.autoReversingDate || "",
      taxMode: j.taxMode,
      showOnCashBasis: j.showOnCashBasis,
      lines: j.lines.map((l) => ({
        description: l.description,
        accountId: l.accountId,
        taxRateId: l.taxRateId || noTaxRate?.id || "",
        debit: l.debit,
        credit: l.credit,
        tracking1OptionId: l.tracking1OptionId || "",
      })),
    });
    setMjModalOpen(true);
  }

  async function submitMj(postImmediately: boolean) {
    const payload = {
      narration: mjForm.narration,
      journalDate: mjForm.journalDate,
      autoReversingDate: mjForm.autoReversingDate || null,
      taxMode: mjForm.taxMode,
      showOnCashBasis: mjForm.showOnCashBasis,
      postImmediately,
      lines: mjForm.lines.map((l) => ({
        description: l.description,
        accountId: l.accountId,
        taxRateId: l.taxRateId || noTaxRate?.id,
        debit: l.debit || "0",
        credit: l.credit || "0",
        tracking1OptionId: l.tracking1OptionId || null,
      })),
    };
    try {
      if (mjEditingId) {
        await api.patch(`/orgs/${orgId}/manual-journals/${mjEditingId}`, payload);
        if (postImmediately) {
          await api.post(`/orgs/${orgId}/manual-journals/${mjEditingId}/post`);
        }
      } else {
        await api.post(`/orgs/${orgId}/manual-journals`, payload);
      }
      onToast("success", postImmediately ? "Manual journal posted to General Ledger." : "Manual journal saved as draft.");
      setMjModalOpen(false);
      await loadRouteData();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function postDraftMj(id: string) {
    try {
      await api.post(`/orgs/${orgId}/manual-journals/${id}/post`);
      onToast("success", "Draft manual journal posted.");
      await loadRouteData();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function voidMj(id: string) {
    try {
      await api.post(`/orgs/${orgId}/manual-journals/${id}/void`);
      onToast("success", "Manual journal voided via reversing journal.");
      await loadRouteData();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // --- FIND & RECODE ---
  async function applyRecode() {
    const ids = Object.entries(recodeSel)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (ids.length === 0 || (!recodeTargetAcc && !recodeTargetTrack)) {
      onToast("error", "Select lines and a target Account or Tracking option.");
      return;
    }
    try {
      await api.post(`/orgs/${orgId}/find-and-recode`, {
        journalLineIds: ids,
        newAccountId: recodeTargetAcc || null,
        newTracking1OptionId: recodeTargetTrack || null,
      });
      onToast("success", `Recoded ${ids.length} journal lines via immutable reversal + repost.`);
      setRecodeSel({});
      await loadRouteData();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // --- CONVERSION BALANCES ---
  async function saveConversion() {
    const entries = Object.entries(convAmounts)
      .map(([accountId, v]) => ({ accountId, debit: v.debit || "0", credit: v.credit || "0" }))
      .filter((e) => parseFloat(e.debit) !== 0 || parseFloat(e.credit) !== 0);
    try {
      await api.post(`/orgs/${orgId}/conversion-balances/post`, {
        conversionDate: convDate,
        entries,
        lockBalances: convLock,
      });
      onToast("success", "Conversion balances posted cleanly (offset via 840 Historical Adjustment if unbalanced).");
      await loadRouteData();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // === RENDER CHART OF ACCOUNTS ===
  if (route === "coa") {
    const filtered = allAccounts.filter((a) => {
      if (!showArchivedCoa && a.status !== "ACTIVE") return false;
      if (coaFilterClass !== "ALL" && a.accountClass !== coaFilterClass) return false;
      const q = coaSearch.trim().toLowerCase();
      if (q && !`${a.code || ""} ${a.name} ${a.accountType}`.toLowerCase().includes(q)) return false;
      return true;
    });

    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Chart of accounts</div>
            <h1 className="x-page-title">
              Chart of Accounts <span className="x-badge blue">{filtered.length} accounts</span>
            </h1>
          </div>
          {canWrite && (
            <button
              className="x-btn x-btn-primary"
              onClick={() => {
                setEditingAcc(null);
                setAccForm({ code: "", name: "", accountType: "EXPENSE", description: "", defaultTaxRateId: "", showOnWatchlist: false });
                setAccModalOpen(true);
              }}
            >
              <Plus size={15} /> Add Account
            </button>
          )}
        </div>
        <main className="x-main">
          <div className="x-card">
            <div className="x-card-header" style={{ flexWrap: "wrap" }}>
              <div className="x-tabs" style={{ marginBottom: 0, borderBottom: "none" }}>
                {["ALL", "ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"].map((c) => (
                  <button
                    key={c}
                    className={`x-tab ${coaFilterClass === c ? "active" : ""}`}
                    onClick={() => setCoaFilterClass(c)}
                  >
                    {c === "ALL" ? "All Accounts" : c.charAt(0) + c.slice(1).toLowerCase()}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12.5 }}>
                  <input type="checkbox" checked={showArchivedCoa} onChange={(e) => setShowArchivedCoa(e.target.checked)} />
                  Show Archived
                </label>
                <div style={{ position: "relative", width: 230 }}>
                  <Search size={14} style={{ position: "absolute", left: 9, top: 9, color: "var(--xui-ink-muted)" }} />
                  <input
                    className="x-input"
                    style={{ paddingLeft: 28 }}
                    placeholder="Search code or name..."
                    value={coaSearch}
                    onChange={(e) => setCoaSearch(e.target.value)}
                  />
                </div>
              </div>
            </div>
            <table className="x-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Tax Rate</th>
                  <th>Flags</th>
                  <th className="num">YTD</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id}>
                    <td style={{ fontWeight: 700 }}>{a.code || "-"}</td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{a.name}</div>
                      {a.description && (
                        <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>{a.description}</div>
                      )}
                    </td>
                    <td>{a.accountType}</td>
                    <td>{a.defaultTaxName || "-"}</td>
                    <td style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {a.isSystemLocked && (
                        <span className="x-badge amber" title="System account cannot be archived or manually journaled">
                          <Lock size={11} /> System Locked
                        </span>
                      )}
                      {a.manualJournalExcluded && !a.isSystemLocked && <span className="x-badge">Excl. MJ</span>}
                      {a.showOnWatchlist && <span className="x-badge blue">Watchlist</span>}
                      {a.status !== "ACTIVE" && <span className="x-badge red">{a.status}</span>}
                    </td>
                    <td className="num">{fmtAud(a.ytdBalance)}</td>
                    <td>
                      {canWrite && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <button
                            className="x-btn x-btn-sm"
                            onClick={() => {
                              setEditingAcc(a);
                              setAccForm({
                                code: a.code || "",
                                name: a.name,
                                accountType: a.accountType,
                                description: a.description || "",
                                defaultTaxRateId: a.defaultTaxRateId || "",
                                showOnWatchlist: a.showOnWatchlist,
                              });
                              setAccModalOpen(true);
                            }}
                          >
                            Edit
                          </button>
                          {!a.isSystemLocked && a.status === "ACTIVE" && (
                            <button className="x-btn x-btn-danger x-btn-sm" onClick={() => archiveAccount(a)}>
                              Archive
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </main>

        {accModalOpen && (
          <div className="x-modal-backdrop" onClick={() => setAccModalOpen(false)}>
            <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
              <div className="x-modal-head">
                <h3 style={{ margin: 0 }}>{editingAcc ? `Edit Account ${editingAcc.code || ""}` : "Add New Account"}</h3>
                <button className="x-btn x-btn-sm" onClick={() => setAccModalOpen(false)}>
                  Close
                </button>
              </div>
              <div className="x-modal-body" style={{ display: "grid", gap: 10 }}>
                <div className="x-grid-2">
                  <div className="x-field">
                    <label>Account Type</label>
                    <select
                      className="x-select"
                      disabled={!!editingAcc}
                      value={accForm.accountType}
                      onChange={(e) => setAccForm({ ...accForm, accountType: e.target.value })}
                    >
                      <option value="REVENUE">Revenue</option>
                      <option value="OTHERINCOME">Other Income</option>
                      <option value="DIRECTCOSTS">Direct Costs</option>
                      <option value="EXPENSE">Expense</option>
                      <option value="OVERHEADS">Overheads</option>
                      <option value="CURRENT">Current Asset</option>
                      <option value="FIXED">Fixed Asset</option>
                      <option value="CURRLIAB">Current Liability</option>
                      <option value="TERMLIAB">Non-current Liability</option>
                      <option value="EQUITY">Equity</option>
                    </select>
                  </div>
                  <div className="x-field">
                    <label>Code</label>
                    <input
                      className="x-input"
                      disabled={!!editingAcc}
                      value={accForm.code}
                      onChange={(e) => setAccForm({ ...accForm, code: e.target.value })}
                      placeholder="e.g. 421"
                    />
                  </div>
                </div>
                <div className="x-field">
                  <label>Name</label>
                  <input className="x-input" value={accForm.name} onChange={(e) => setAccForm({ ...accForm, name: e.target.value })} />
                </div>
                <div className="x-field">
                  <label>Default Tax Rate</label>
                  <select
                    className="x-select"
                    value={accForm.defaultTaxRateId}
                    onChange={(e) => setAccForm({ ...accForm, defaultTaxRateId: e.target.value })}
                  >
                    <option value="">-- Select Default Tax --</option>
                    {taxRates.map((tr) => (
                      <option key={tr.id} value={tr.id}>
                        {tr.name} ({tr.ratePercent}%)
                      </option>
                    ))}
                  </select>
                </div>
                <div className="x-field">
                  <label>Description</label>
                  <input className="x-input" value={accForm.description} onChange={(e) => setAccForm({ ...accForm, description: e.target.value })} />
                </div>
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={accForm.showOnWatchlist}
                    onChange={(e) => setAccForm({ ...accForm, showOnWatchlist: e.target.checked })}
                  />
                  Show on Dashboard Account Watchlist
                </label>
              </div>
              <div className="x-modal-foot">
                <button className="x-btn" onClick={() => setAccModalOpen(false)}>
                  Cancel
                </button>
                <button className="x-btn x-btn-primary" onClick={saveAccount}>
                  Save Account
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // === RENDER MANUAL JOURNALS ===
  if (route === "manual-journals") {
    const visibleMj = journals.filter((j) => mjTab === "ALL" || j.status === mjTab);
    const sumDr = mjForm.lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0);
    const sumCr = mjForm.lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0);
    const isBalanced = Math.abs(sumDr - sumCr) < 0.005 && sumDr > 0;

    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Manual journals</div>
            <h1 className="x-page-title">
              Manual Journals <span className="x-badge blue">{mjAccounts.length} eligible AU accounts</span>
            </h1>
          </div>
          {canWrite && (
            <button className="x-btn x-btn-primary" onClick={openNewMj}>
              <Plus size={15} /> New Journal
            </button>
          )}
        </div>
        <main className="x-main">
          {!isAdviser && (
            <div className="x-alert warn">
              <AlertTriangle size={16} /> Standard/Read-Only role active: Posting Manual Journals requires Adviser permission (enforced by server).
            </div>
          )}
          <div className="x-card">
            <div className="x-card-header">
              <div className="x-tabs" style={{ marginBottom: 0, borderBottom: "none" }}>
                {["ALL", "POSTED", "DRAFT", "VOIDED"].map((st) => (
                  <button key={st} className={`x-tab ${mjTab === st ? "active" : ""}`} onClick={() => setMjTab(st)}>
                    {st}
                  </button>
                ))}
              </div>
            </div>
            <table className="x-table">
              <thead>
                <tr>
                  <th>Narration</th>
                  <th>Date</th>
                  <th>Auto-Reverse</th>
                  <th>Tax Mode</th>
                  <th>Status</th>
                  <th>GL #</th>
                  <th className="num">Debit</th>
                  <th className="num">Credit</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleMj.map((j) => (
                  <tr key={j.id}>
                    <td style={{ fontWeight: 600 }}>{j.narration}</td>
                    <td>{j.journalDate}</td>
                    <td>{j.autoReversingDate || "-"}</td>
                    <td>{j.taxMode}</td>
                    <td>
                      <span
                        className={`x-badge ${
                          j.status === "POSTED" ? "green" : j.status === "DRAFT" ? "blue" : "red"
                        }`}
                      >
                        {j.status}
                      </span>
                    </td>
                    <td>
                      {j.postedJournalNumber ? `#${j.postedJournalNumber}` : "-"}
                      {j.reversalJournalNumber ? ` (Rev #${j.reversalJournalNumber})` : ""}
                    </td>
                    <td className="num">{fmtAud(j.totalDebit)}</td>
                    <td className="num">{fmtAud(j.totalCredit)}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        {j.status === "DRAFT" && canWrite && (
                          <>
                            <button className="x-btn x-btn-sm" onClick={() => openEditMj(j)}>
                              Edit
                            </button>
                            <button className="x-btn x-btn-green x-btn-sm" onClick={() => postDraftMj(j.id)}>
                              Post
                            </button>
                          </>
                        )}
                        {j.status === "POSTED" && isAdviser && (
                          <button className="x-btn x-btn-danger x-btn-sm" onClick={() => voidMj(j.id)}>
                            <Undo2 size={13} /> Void
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {visibleMj.length === 0 && (
                  <tr>
                    <td colSpan={9} style={{ textAlign: "center", padding: 28, color: "var(--xui-ink-muted)" }}>
                      No manual journals in this view.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </main>

        {mjModalOpen && (
          <div className="x-modal-backdrop" onClick={() => setMjModalOpen(false)}>
            <div className="x-modal" onClick={(e) => e.stopPropagation()}>
              <div className="x-modal-head">
                <h3 style={{ margin: 0 }}>{mjEditingId ? "Edit Draft Manual Journal" : "New Manual Journal"}</h3>
                <button className="x-btn x-btn-sm" onClick={() => setMjModalOpen(false)}>
                  Close
                </button>
              </div>
              <div className="x-modal-body">
                <div className="x-grid-4" style={{ marginBottom: 14 }}>
                  <div className="x-field" style={{ gridColumn: "span 2" }}>
                    <label>Narration</label>
                    <input
                      className="x-input"
                      value={mjForm.narration}
                      onChange={(e) => setMjForm({ ...mjForm, narration: e.target.value })}
                      placeholder="e.g. Monthly office rent accrual"
                    />
                  </div>
                  <div className="x-field">
                    <label>Date</label>
                    <input
                      type="date"
                      className="x-input"
                      value={mjForm.journalDate}
                      onChange={(e) => setMjForm({ ...mjForm, journalDate: e.target.value })}
                    />
                  </div>
                  <div className="x-field">
                    <label>Auto-reversing Date (optional)</label>
                    <input
                      type="date"
                      className="x-input"
                      value={mjForm.autoReversingDate}
                      onChange={(e) => setMjForm({ ...mjForm, autoReversingDate: e.target.value })}
                    />
                  </div>
                </div>
                <div style={{ display: "flex", gap: 18, alignItems: "center", marginBottom: 12 }}>
                  <div className="x-field" style={{ width: 220 }}>
                    <label>Amounts Are</label>
                    <select
                      className="x-select"
                      value={mjForm.taxMode}
                      onChange={(e) =>
                        setMjForm({ ...mjForm, taxMode: e.target.value as "NO_TAX" | "EXCLUSIVE" | "INCLUSIVE" })
                      }
                    >
                      <option value="NO_TAX">No Tax</option>
                      <option value="EXCLUSIVE">Tax Exclusive</option>
                      <option value="INCLUSIVE">Tax Inclusive</option>
                    </select>
                  </div>
                  <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 14 }}>
                    <input
                      type="checkbox"
                      checked={mjForm.showOnCashBasis}
                      onChange={(e) => setMjForm({ ...mjForm, showOnCashBasis: e.target.checked })}
                    />
                    Show journal on cash basis reports
                  </label>
                </div>

                <table className="x-table">
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th>Account (47 AU eligible)</th>
                      <th>Tax Rate</th>
                      {track1 && <th>{track1.name}</th>}
                      <th className="num" style={{ width: 115 }}>
                        Debit AUD
                      </th>
                      <th className="num" style={{ width: 115 }}>
                        Credit AUD
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {mjForm.lines.map((l, idx) => (
                      <tr key={idx}>
                        <td>
                          <input
                            className="x-input"
                            value={l.description}
                            onChange={(e) => {
                              const next = [...mjForm.lines];
                              next[idx] = { ...l, description: e.target.value };
                              setMjForm({ ...mjForm, lines: next });
                            }}
                          />
                        </td>
                        <td>
                          <select
                            className="x-select"
                            value={l.accountId}
                            onChange={(e) => {
                              const next = [...mjForm.lines];
                              next[idx] = { ...l, accountId: e.target.value };
                              setMjForm({ ...mjForm, lines: next });
                            }}
                          >
                            {mjAccounts.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.code} - {a.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <select
                            className="x-select"
                            disabled={mjForm.taxMode === "NO_TAX"}
                            value={l.taxRateId}
                            onChange={(e) => {
                              const next = [...mjForm.lines];
                              next[idx] = { ...l, taxRateId: e.target.value };
                              setMjForm({ ...mjForm, lines: next });
                            }}
                          >
                            {taxRates.map((tr) => (
                              <option key={tr.id} value={tr.id}>
                                {tr.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        {track1 && (
                          <td>
                            <select
                              className="x-select"
                              value={l.tracking1OptionId}
                              onChange={(e) => {
                                const next = [...mjForm.lines];
                                next[idx] = { ...l, tracking1OptionId: e.target.value };
                                setMjForm({ ...mjForm, lines: next });
                              }}
                            >
                              <option value="">--</option>
                              {track1.options.map((o) => (
                                <option key={o.id} value={o.id}>
                                  {o.name}
                                </option>
                              ))}
                            </select>
                          </td>
                        )}
                        <td>
                          <input
                            className="x-input num"
                            value={l.debit}
                            onChange={(e) => {
                              const next = [...mjForm.lines];
                              next[idx] = { ...l, debit: e.target.value };
                              setMjForm({ ...mjForm, lines: next });
                            }}
                          />
                        </td>
                        <td>
                          <input
                            className="x-input num"
                            value={l.credit}
                            onChange={(e) => {
                              const next = [...mjForm.lines];
                              next[idx] = { ...l, credit: e.target.value };
                              setMjForm({ ...mjForm, lines: next });
                            }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
                  <button
                    className="x-btn x-btn-sm"
                    onClick={() =>
                      setMjForm({
                        ...mjForm,
                        lines: [
                          ...mjForm.lines,
                          {
                            description: "",
                            accountId: mjAccounts[0]?.id || "",
                            taxRateId: noTaxRate?.id || "",
                            debit: "0.00",
                            credit: "0.00",
                            tracking1OptionId: "",
                          },
                        ],
                      })
                    }
                  >
                    + Add a new line
                  </button>
                  <div style={{ display: "flex", gap: 20, fontWeight: 700 }}>
                    <span>Total Debit: {fmtAud(sumDr)}</span>
                    <span>Total Credit: {fmtAud(sumCr)}</span>
                    <span className={`x-badge ${isBalanced ? "green" : "red"}`}>
                      {isBalanced ? "Balanced" : "Out of Balance"}
                    </span>
                  </div>
                </div>
              </div>
              <div className="x-modal-foot">
                <button className="x-btn" onClick={() => setMjModalOpen(false)}>
                  Cancel
                </button>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="x-btn" onClick={() => submitMj(false)}>
                    Save as Draft
                  </button>
                  <button className="x-btn x-btn-green" disabled={!isBalanced} onClick={() => submitMj(true)}>
                    Post Journal
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // === RENDER FIND & RECODE ===
  if (route === "find-recode") {
    const nonLocked = allAccounts.filter((a) => !a.isSystemLocked && a.accountType !== "BANK" && a.status === "ACTIVE");
    const selCount = Object.values(recodeSel).filter(Boolean).length;
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Find and recode</div>
            <h1 className="x-page-title">Find and Recode</h1>
          </div>
        </div>
        <main className="x-main">
          {!isAdviser && (
            <div className="x-alert warn">
              <AlertTriangle size={16} /> Find and Recode requires the <strong>Adviser</strong> role.
            </div>
          )}
          <div className="x-card" style={{ marginBottom: 16 }}>
            <div className="x-card-body" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <div className="x-field" style={{ minWidth: 260 }}>
                <label>Filter by Account</label>
                <select className="x-select" value={recodeFilterAcc} onChange={(e) => setRecodeFilterAcc(e.target.value)}>
                  <option value="">All recodable accounts</option>
                  {nonLocked.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <button className="x-btn x-btn-primary" onClick={() => loadRouteData()}>
                <Search size={14} /> Search
              </button>
              <div style={{ flex: 1 }} />
              <div className="x-field" style={{ minWidth: 240 }}>
                <label>Recode To Account</label>
                <select className="x-select" value={recodeTargetAcc} onChange={(e) => setRecodeTargetAcc(e.target.value)}>
                  <option value="">-- Choose Target Account --</option>
                  {nonLocked.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </div>
              {track1 && (
                <div className="x-field" style={{ minWidth: 180 }}>
                  <label>Recode {track1.name}</label>
                  <select className="x-select" value={recodeTargetTrack} onChange={(e) => setRecodeTargetTrack(e.target.value)}>
                    <option value="">-- No Change --</option>
                    {track1.options.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <button className="x-btn x-btn-green" disabled={!isAdviser || selCount === 0} onClick={applyRecode}>
                Recode ({selCount})
              </button>
            </div>
          </div>

          <div className="x-card" style={{ marginBottom: 16 }}>
            <table className="x-table">
              <thead>
                <tr>
                  <th style={{ width: 32 }}></th>
                  <th>Date</th>
                  <th>Jnl #</th>
                  <th>Source</th>
                  <th>Contact</th>
                  <th>Account</th>
                  <th>Description</th>
                  <th className="num">Debit</th>
                  <th className="num">Credit</th>
                </tr>
              </thead>
              <tbody>
                {recodeLines.map((rl) => (
                  <tr key={rl.journalLineId}>
                    <td>
                      <input
                        type="checkbox"
                        checked={!!recodeSel[rl.journalLineId]}
                        onChange={(e) => setRecodeSel({ ...recodeSel, [rl.journalLineId]: e.target.checked })}
                      />
                    </td>
                    <td>{rl.date}</td>
                    <td>#{rl.journalNumber}</td>
                    <td>
                      <span className="x-badge">{rl.sourceType}</span>
                    </td>
                    <td>{rl.contactName || "-"}</td>
                    <td>
                      {rl.accountCode} {rl.accountName}
                    </td>
                    <td>{rl.description || "-"}</td>
                    <td className="num">{fmtAud(rl.debit)}</td>
                    <td className="num">{fmtAud(rl.credit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {recodeHistory.length > 0 && (
            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Recode History Batches</div>
              </div>
              <div className="x-card-body">
                {recodeHistory.map((h, i) => (
                  <div key={i} style={{ padding: "6px 0", borderBottom: "1px solid #eef1f5" }}>
                    {String(h["summary"] || JSON.stringify(h))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>
      </>
    );
  }

  // === RENDER CONVERSION BALANCES ===
  if (route === "conversion-balances") {
    const totDr = Object.values(convAmounts).reduce((s, v) => s + (parseFloat(v.debit) || 0), 0);
    const totCr = Object.values(convAmounts).reduce((s, v) => s + (parseFloat(v.credit) || 0), 0);
    const diff = totDr - totCr;
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Advanced &gt; Conversion balances</div>
            <h1 className="x-page-title">Conversion Balances</h1>
          </div>
          {isAdviser && (
            <button className="x-btn x-btn-green" onClick={saveConversion}>
              Save & Post Conversion Balances
            </button>
          )}
        </div>
        <main className="x-main">
          <div className="x-card">
            <div className="x-card-header" style={{ flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                <div className="x-field">
                  <label>Conversion Date</label>
                  <input type="date" className="x-input" value={convDate} onChange={(e) => setConvDate(e.target.value)} />
                </div>
                <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 14 }}>
                  <input type="checkbox" checked={convLock} onChange={(e) => setConvLock(e.target.checked)} />
                  Lock balances on save
                </label>
                {convData?.conversionLockedAt && (
                  <span className="x-badge green" style={{ marginTop: 14 }}>
                    Locked at {convData.conversionLockedAt.slice(0, 10)}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 18 }}>
                <span>Total Debit: <strong>{fmtAud(totDr)}</strong></span>
                <span>Total Credit: <strong>{fmtAud(totCr)}</strong></span>
                <span>
                  840 Historical Adj:{" "}
                  <strong style={{ color: Math.abs(diff) > 0.005 ? "var(--xui-amber)" : "var(--xui-green)" }}>
                    {fmtAud(diff)}
                  </strong>
                </span>
              </div>
            </div>
            <table className="x-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Account</th>
                  <th>Type</th>
                  <th className="num" style={{ width: 150 }}>
                    Debit AUD
                  </th>
                  <th className="num" style={{ width: 150 }}>
                    Credit AUD
                  </th>
                </tr>
              </thead>
              <tbody>
                {allAccounts
                  .filter((a) => a.status === "ACTIVE" && a.systemAccount !== "HISTORICAL_ADJ")
                  .map((a) => {
                    const row = convAmounts[a.id] || { debit: "", credit: "" };
                    return (
                      <tr key={a.id}>
                        <td style={{ fontWeight: 700 }}>{a.code || "-"}</td>
                        <td>{a.name}</td>
                        <td>{a.accountType}</td>
                        <td>
                          <input
                            className="x-input num"
                            placeholder="0.00"
                            value={row.debit}
                            onChange={(e) =>
                              setConvAmounts({ ...convAmounts, [a.id]: { debit: e.target.value, credit: row.credit } })
                            }
                          />
                        </td>
                        <td>
                          <input
                            className="x-input num"
                            placeholder="0.00"
                            value={row.credit}
                            onChange={(e) =>
                              setConvAmounts({ ...convAmounts, [a.id]: { debit: row.debit, credit: e.target.value } })
                            }
                          />
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </main>
      </>
    );
  }

  // === RENDER ASSURANCE DASHBOARD ===
  if (route === "assurance") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Advanced &gt; Assurance dashboard</div>
            <h1 className="x-page-title">
              <ShieldCheck size={20} color="var(--xui-nav-blue)" /> Assurance Dashboard
            </h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-grid-2">
            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Duplicate Contact Bank Accounts</div>
                <span className={`x-badge ${assurance?.duplicateBankContacts.length ? "amber" : "green"}`}>
                  {assurance?.duplicateBankContacts.length ?? 0}
                </span>
              </div>
              <div className="x-card-body">
                {assurance?.duplicateBankContacts.length ? (
                  assurance.duplicateBankContacts.map((d, i) => (
                    <div key={i} style={{ padding: "6px 0", borderBottom: "1px solid #eef1f5" }}>
                      <strong>{d.bank_bsb_account}</strong> — Shared by {d.cnt} contacts ({d.names})
                    </div>
                  ))
                ) : (
                  <div style={{ color: "var(--xui-green)", display: "flex", gap: 6, alignItems: "center" }}>
                    <CheckCircle2 size={16} /> No duplicate supplier/customer BSB accounts detected.
                  </div>
                )}
              </div>
            </div>

            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Manual Bank Statement Imports</div>
                <span className="x-badge blue">{assurance?.manualBankLines.length ?? 0}</span>
              </div>
              <div className="x-card-body">
                {assurance?.manualBankLines.length ? (
                  assurance.manualBankLines.slice(0, 10).map((m) => (
                    <div key={m.id} style={{ padding: "5px 0", borderBottom: "1px solid #eef1f5" }}>
                      {m.tx_date} • {m.payee || m.description || "Manual line"} ({fmtAud(m.amount_cents / 100)})
                    </div>
                  ))
                ) : (
                  <div style={{ color: "var(--xui-ink-muted)" }}>No manually flagged bank lines.</div>
                )}
              </div>
            </div>

            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Voided Invoices / Bills (Recent 20)</div>
                <span className="x-badge">{assurance?.voidedDocuments.length ?? 0}</span>
              </div>
              <div className="x-card-body">
                {assurance?.voidedDocuments.length ? (
                  assurance.voidedDocuments.map((v) => (
                    <div key={v.id} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0" }}>
                      <span>
                        <strong>{v.number}</strong> ({v.type}) • {v.date}
                      </span>
                      <span className="num">{fmtAud(v.total)}</span>
                    </div>
                  ))
                ) : (
                  <div style={{ color: "var(--xui-ink-muted)" }}>No voided commercial documents.</div>
                )}
              </div>
            </div>

            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">User Audit Activity</div>
              </div>
              <div className="x-card-body">
                {(assurance?.userActivity || []).map((u, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0" }}>
                    <strong>{u.actor_name}</strong>
                    <span>
                      {u.actions} actions (last: {u.last_active.slice(0, 16).replace("T", " ")})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </>
    );
  }

  // === RENDER IMMUTABLE HISTORY & NOTES AUDIT LOG ===
  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Accounting &gt; Advanced &gt; History and notes</div>
          <h1 className="x-page-title">
            <History size={20} color="var(--xui-nav-blue)" /> History & Notes Activity (Append-Only)
          </h1>
        </div>
      </div>
      <main className="x-main">
        <div className="x-card">
          <table className="x-table">
            <thead>
              <tr>
                <th>Timestamp (UTC)</th>
                <th>Actor</th>
                <th>Entity</th>
                <th>Action</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((al) => (
                <tr key={al.id}>
                  <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{al.created_at.slice(0, 19).replace("T", " ")}</td>
                  <td>{al.actor_name}</td>
                  <td>
                    <span className="x-badge">{al.entity_type}</span>
                  </td>
                  <td>
                    <span className="x-badge blue">{al.action}</span>
                  </td>
                  <td>{al.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
