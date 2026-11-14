import { useEffect, useState } from "react";
import {
  ArrowLeftRight,
  Check,
  FileSpreadsheet,
  Plus,
  RefreshCw,
  Sliders,
  Trash2,
  Undo2,
  Upload,
} from "lucide-react";
import { api, fmtAud } from "../api";
import type {
  AccountItem,
  BankAccountSummary,
  ContactItem,
  TaxRateItem,
  TrackingCategory,
  UserRole,
} from "../types";
import type { RouteKey } from "./TopNav";

interface StatementSuggestionLine {
  id: string;
  txDate: string;
  amount: string;
  spent: string | null;
  received: string | null;
  payee: string | null;
  description: string | null;
  reference: string | null;
  chequeNumber: string | null;
  discussNote: string | null;
  version: number;
  suggestionType: "NONE" | "MATCH_EXISTING_PAYMENT" | "MATCH_INVOICE" | "BANK_RULE";
  matchedPayment: { paymentId: string; amount: string; reference?: string | null; invoiceNumber?: string } | null;
  matchedDocument: { invoiceId: string; invoiceNumber: string; contactName: string; amountDue: string } | null;
  matchedRule: {
    ruleId: string;
    ruleName: string;
    ruleType: string;
    targetBankId?: string | null;
    contactId?: string | null;
    lines?: { description: string; accountId: string; taxRateId: string; amount: string; tracking1OptionId?: string | null }[];
  } | null;
}

interface SuggestionsResponse {
  bankAccount: { id: string; name: string; statementBalance: string; bookBalance: string; difference: string };
  statementLines: StatementSuggestionLine[];
  openDocuments: {
    id: string;
    invoiceNumber: string;
    invoiceType: string;
    contactId: string;
    contactName: string;
    issueDate: string;
    dueDate: string;
    total: string;
    amountDue: string;
  }[];
  otherBankAccounts: { id: string; name: string }[];
}

interface StatementLineRaw {
  id: string;
  txDate: string;
  amount: string;
  payee: string | null;
  description: string | null;
  reference: string | null;
  occurrenceIdx: number;
  reconcileStatus: "UNRECONCILED" | "RECONCILED" | "DELETED";
  matchedEntityType: string | null;
  matchedEntityId: string | null;
  reconciledAt: string | null;
  version: number;
}

interface BankTxItem {
  id: string;
  txType: string;
  bankAccountId: string;
  bankAccountName: string;
  contactName: string | null;
  txDate: string;
  reference: string | null;
  total: string;
  isReconciled: boolean;
  status: string;
  journalNumber: number | null;
}

interface BankRuleItem {
  id: string;
  name: string;
  ruleType: "SPEND" | "RECEIVE" | "TRANSFER";
  matchStrategy: "ALL" | "ANY";
  priorityOrder: number;
  conditions: { field: string; operator: string; value: string }[];
  contactId: string | null;
  percentLines: { description?: string; percent: string; accountId: string; taxRateId: string; tracking1OptionId?: string | null }[];
}

interface Props {
  orgId: string;
  route: RouteKey;
  role: UserRole;
  selectedBankId: string;
  onSelectBankId: (id: string) => void;
  onNavigate: (route: RouteKey) => void;
  onToast: (type: "success" | "error" | "info", msg: string) => void;
}

export function BankingReconcileView({
  orgId,
  route,
  role,
  selectedBankId,
  onSelectBankId,
  onNavigate,
  onToast,
}: Props) {
  const canWrite = role !== "READONLY";
  const [bankAccounts, setBankAccounts] = useState<BankAccountSummary[]>([]);
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [taxRates, setTaxRates] = useState<TaxRateItem[]>([]);
  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [tracking, setTracking] = useState<TrackingCategory[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionsResponse | null>(null);
  const [statementAll, setStatementAll] = useState<StatementLineRaw[]>([]);
  const [bankTxs, setBankTxs] = useState<BankTxItem[]>([]);
  const [bankRules, setBankRules] = useState<BankRuleItem[]>([]);
  const [subTab, setSubTab] = useState<"reconcile" | "cashcoding" | "statements" | "transactions">("reconcile");
  const [loading, setLoading] = useState(false);

  // Per statement-line interactive right-pane state
  const [lineTab, setLineTab] = useState<Record<string, "match" | "create" | "transfer" | "discuss">>({});
  const [createDrafts, setCreateDrafts] = useState<
    Record<string, { contactId: string; accountId: string; taxRateId: string; description: string; tracking1OptionId: string }>
  >({});
  const [matchSelections, setMatchSelections] = useState<Record<string, { invoiceIds: string[]; adjAmount: string; adjAccountId: string }>>({});
  const [transferTargets, setTransferTargets] = useState<Record<string, string>>({});

  // Cash coding grid state
  const [ccSelected, setCcSelected] = useState<Record<string, boolean>>({});
  const [ccEdits, setCcEdits] = useState<
    Record<string, { accountId: string; taxRateId: string; description: string; tracking1OptionId: string }>
  >({});

  // Modals: CSV Import, Add Bank Account, New Bank Rule
  const [csvModalOpen, setCsvModalOpen] = useState(false);
  const [csvText, setCsvText] = useState(
    "Date,Amount,Payee,Description,Reference\n2026-10-20,-132.00,Stationery Depot,Office pens and paper,INV-SD-99\n2026-10-21,550.00,Ridgeway University,Workshop fee deposit,DEP-550"
  );
  const [addBankOpen, setAddBankOpen] = useState(false);
  const [newBankName, setNewBankName] = useState("");
  const [newBankCode, setNewBankCode] = useState("095");
  const [newBankBsb, setNewBankBsb] = useState("");
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [ruleForm, setRuleForm] = useState({
    id: "",
    name: "",
    ruleType: "SPEND" as "SPEND" | "RECEIVE" | "TRANSFER",
    matchStrategy: "ALL" as "ALL" | "ANY",
    field: "PAYEE",
    operator: "CONTAINS",
    value: "",
    contactId: "",
    accountId: "",
    taxRateId: "",
    description: "",
  });

  const nonBankAccounts = accounts.filter((a) => !a.isSystemLocked && a.accountType !== "BANK");
  const track1 = tracking[0] || null;

  async function loadBase() {
    const [bks, accs, trs, cts, tks] = await Promise.all([
      api.get<BankAccountSummary[]>(`/orgs/${orgId}/bank-accounts`),
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts`),
      api.get<TaxRateItem[]>(`/orgs/${orgId}/tax-rates`),
      api.get<ContactItem[]>(`/orgs/${orgId}/contacts`),
      api.get<TrackingCategory[]>(`/orgs/${orgId}/tracking-categories`),
    ]);
    setBankAccounts(bks);
    setAccounts(accs);
    setTaxRates(trs);
    setContacts(cts);
    setTracking(tks);
    if (!selectedBankId && bks.length > 0) {
      onSelectBankId(bks[0].id);
      return bks[0].id;
    }
    return selectedBankId || bks[0]?.id || "";
  }

  async function loadBankDetails(bankId: string) {
    if (!bankId) return;
    setLoading(true);
    try {
      const [sugg, stmts, txs, rls] = await Promise.all([
        api.get<SuggestionsResponse>(`/orgs/${orgId}/bank-accounts/${bankId}/suggestions`),
        api.get<StatementLineRaw[]>(`/orgs/${orgId}/bank-accounts/${bankId}/statement-lines?status=ALL`),
        api.get<BankTxItem[]>(`/orgs/${orgId}/bank-accounts/${bankId}/transactions`),
        api.get<BankRuleItem[]>(`/orgs/${orgId}/bank-rules`),
      ]);
      setSuggestions(sugg);
      setStatementAll(stmts);
      setBankTxs(txs);
      setBankRules(rls);
      setCcSelected({});
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadBase()
      .then((bid) => loadBankDetails(bid))
      .catch((e: Error) => onToast("error", e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  useEffect(() => {
    if (selectedBankId) {
      loadBankDetails(selectedBankId).catch((e: Error) => onToast("error", e.message));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBankId]);

  useEffect(() => {
    if (route === "cash-coding") setSubTab("cashcoding");
    else if (route === "bank-reconcile") setSubTab("reconcile");
  }, [route]);

  const activeBank = bankAccounts.find((b) => b.id === selectedBankId) || bankAccounts[0] || null;
  const defaultExpenseAcc = nonBankAccounts.find((a) => a.code === "404") || nonBankAccounts[0];
  const defaultIncomeAcc = nonBankAccounts.find((a) => a.code === "200") || nonBankAccounts[0];
  const defaultGstTax = taxRates.find((t) => t.code === "INPUT") || taxRates.find((t) => t.code === "OUTPUT") || taxRates[0];

  function getDraft(line: StatementSuggestionLine) {
    const existing = createDrafts[line.id];
    if (existing) return existing;
    const isSpent = parseFloat(line.amount) < 0;
    return {
      contactId: line.matchedRule?.contactId || "",
      accountId:
        line.matchedRule?.lines?.[0]?.accountId ||
        (isSpent ? defaultExpenseAcc?.id : defaultIncomeAcc?.id) ||
        "",
      taxRateId:
        line.matchedRule?.lines?.[0]?.taxRateId ||
        (isSpent ? taxRates.find((t) => t.code === "INPUT")?.id : taxRates.find((t) => t.code === "OUTPUT")?.id) ||
        defaultGstTax?.id ||
        "",
      description: line.matchedRule?.lines?.[0]?.description || line.description || line.payee || "Bank Transaction",
      tracking1OptionId: line.matchedRule?.lines?.[0]?.tracking1OptionId || "",
    };
  }

  async function handleOkSuggestion(line: StatementSuggestionLine) {
    if (!activeBank) return;
    try {
      if (line.suggestionType === "MATCH_EXISTING_PAYMENT" && line.matchedPayment) {
        await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
          statementLineId: line.id,
          version: line.version,
          action: "MATCH_EXISTING_PAYMENT",
          paymentId: line.matchedPayment.paymentId,
        });
      } else if (line.suggestionType === "MATCH_INVOICE" && line.matchedDocument) {
        await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
          statementLineId: line.id,
          version: line.version,
          action: "MATCH_INVOICE",
          matchAllocations: [{ invoiceId: line.matchedDocument.invoiceId, amount: Math.abs(parseFloat(line.amount)).toFixed(2) }],
        });
      } else if (line.suggestionType === "BANK_RULE" && line.matchedRule) {
        if (line.matchedRule.ruleType === "TRANSFER" && line.matchedRule.targetBankId) {
          await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
            statementLineId: line.id,
            version: line.version,
            action: "TRANSFER",
            transferBankAccountId: line.matchedRule.targetBankId,
          });
        } else {
          await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
            statementLineId: line.id,
            version: line.version,
            action: "CREATE_BANK_TX",
            bankRuleId: line.matchedRule.ruleId,
          });
        }
      } else {
        // Check if user filled Create draft on the right
        const draft = getDraft(line);
        await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
          statementLineId: line.id,
          version: line.version,
          action: "CREATE_BANK_TX",
          createPayload: {
            contactId: draft.contactId || null,
            reference: line.reference || null,
            taxMode: "INCLUSIVE",
            lines: [
              {
                description: draft.description,
                accountId: draft.accountId,
                taxRateId: draft.taxRateId,
                amount: Math.abs(parseFloat(line.amount)).toFixed(2),
                tracking1OptionId: draft.tracking1OptionId || null,
              },
            ],
          },
        });
      }
      onToast("success", `Reconciled statement line (${line.txDate}) successfully.`);
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleMatchManual(line: StatementSuggestionLine) {
    if (!activeBank) return;
    const sel = matchSelections[line.id];
    if (!sel || sel.invoiceIds.length === 0) {
      onToast("error", "Select at least one open invoice or bill to match.");
      return;
    }
    const allocs = sel.invoiceIds.map((iid) => {
      const doc = suggestions?.openDocuments.find((d) => d.id === iid);
      return { invoiceId: iid, amount: doc?.amountDue || "0.00" };
    });
    try {
      const adjAmt = parseFloat(sel.adjAmount || "0");
      await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
        statementLineId: line.id,
        version: line.version,
        action: "MATCH_INVOICE",
        matchAllocations: allocs,
        minorAdjustment: adjAmt !== 0 ? sel.adjAmount : undefined,
        adjustmentAccountId: adjAmt !== 0 ? sel.adjAccountId || defaultExpenseAcc?.id : undefined,
      });
      onToast("success", "Matched & reconciled against selected documents.");
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleTransfer(line: StatementSuggestionLine) {
    if (!activeBank) return;
    const targetId = transferTargets[line.id] || suggestions?.otherBankAccounts?.[0]?.id;
    if (!targetId) {
      onToast("error", "No destination bank account available for transfer.");
      return;
    }
    try {
      await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/reconcile`, {
        statementLineId: line.id,
        version: line.version,
        action: "TRANSFER",
        transferBankAccountId: targetId,
      });
      onToast("success", "Inter-bank transfer posted & reconciled.");
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleCashCodingApply() {
    if (!activeBank || !suggestions) return;
    const selectedLines = suggestions.statementLines.filter((l) => ccSelected[l.id]);
    if (selectedLines.length === 0) {
      onToast("error", "Tick at least one statement line in Cash Coding.");
      return;
    }
    const items = selectedLines.map((l) => {
      const ed = ccEdits[l.id];
      const isSpent = parseFloat(l.amount) < 0;
      return {
        statementLineId: l.id,
        version: l.version,
        accountId: ed?.accountId || (isSpent ? defaultExpenseAcc?.id : defaultIncomeAcc?.id),
        taxRateId: ed?.taxRateId || (isSpent ? taxRates.find((t) => t.code === "INPUT")?.id : taxRates.find((t) => t.code === "OUTPUT")?.id),
        description: ed?.description || l.description || l.payee || "Cash Coding",
        tracking1OptionId: ed?.tracking1OptionId || null,
      };
    });
    try {
      const res = await api.post<{ reconciledCount: number }>(
        `/orgs/${orgId}/bank-accounts/${activeBank.id}/cash-coding/apply`,
        { items }
      );
      onToast("success", `Cash Coding reconciled ${res.reconciledCount} statement lines.`);
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleImportCsv() {
    if (!activeBank) return;
    try {
      const res = await api.post<{ importedCount: number; skippedDuplicates: number }>(
        `/orgs/${orgId}/bank-accounts/${activeBank.id}/statement-lines/import`,
        { csvText }
      );
      onToast("success", `Imported ${res.importedCount} lines (${res.skippedDuplicates} duplicates skipped).`);
      setCsvModalOpen(false);
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleUnreconcile(stmtId: string) {
    if (!activeBank) return;
    try {
      await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/unreconcile`, { statementLineId: stmtId });
      onToast("success", "Statement line unreconciled.");
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleRemoveAndRedo(stmtId: string) {
    if (!activeBank) return;
    try {
      await api.post(`/orgs/${orgId}/bank-accounts/${activeBank.id}/remove-redo`, { statementLineId: stmtId });
      onToast("success", "Remove & Redo reversed the matched GL transaction; statement line awaits re-reconciliation.");
      await loadBase();
      await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleAddBankAccount() {
    if (!newBankName.trim()) {
      onToast("error", "Bank account name is required.");
      return;
    }
    try {
      await api.post(`/orgs/${orgId}/accounts`, {
        code: newBankCode.trim() || null,
        name: newBankName.trim(),
        accountType: "BANK",
        bankAccountNumber: newBankBsb.trim() || null,
      });
      onToast("success", `Bank account '${newBankName}' created.`);
      setAddBankOpen(false);
      setNewBankName("");
      const bid = await loadBase();
      await loadBankDetails(bid);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleSaveRule() {
    if (!ruleForm.name.trim() || !ruleForm.value.trim() || !ruleForm.accountId) {
      onToast("error", "Rule name, condition value, and target account are required.");
      return;
    }
    const payload = {
      name: ruleForm.name.trim(),
      ruleType: ruleForm.ruleType,
      matchStrategy: ruleForm.matchStrategy,
      priorityOrder: 10,
      conditions: [{ field: ruleForm.field, operator: ruleForm.operator, value: ruleForm.value.trim() }],
      contactId: ruleForm.contactId || null,
      percentLines: [
        {
          description: ruleForm.description || ruleForm.name.trim(),
          percent: "100",
          accountId: ruleForm.accountId,
          taxRateId: ruleForm.taxRateId || defaultGstTax?.id,
        },
      ],
    };
    try {
      if (ruleForm.id) {
        await api.put(`/orgs/${orgId}/bank-rules/${ruleForm.id}`, payload);
        onToast("success", "Bank rule updated.");
      } else {
        await api.post(`/orgs/${orgId}/bank-rules`, payload);
        onToast("success", "Bank rule created.");
      }
      setRuleModalOpen(false);
      if (activeBank) await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function handleDeleteRule(ruleId: string) {
    try {
      await api.del(`/orgs/${orgId}/bank-rules/${ruleId}`);
      onToast("success", "Bank rule archived.");
      if (activeBank) await loadBankDetails(activeBank.id);
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // --- BANK RULES PAGE ---
  if (route === "bank-rules") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Bank Rules</div>
            <h1 className="x-page-title">Bank Rules</h1>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="x-btn" onClick={() => onNavigate("bank-reconcile")}>
              Back to Reconcile
            </button>
            {canWrite && (
              <button
                className="x-btn x-btn-primary"
                onClick={() => {
                  setRuleForm({
                    id: "",
                    name: "",
                    ruleType: "SPEND",
                    matchStrategy: "ALL",
                    field: "PAYEE",
                    operator: "CONTAINS",
                    value: "",
                    contactId: "",
                    accountId: defaultExpenseAcc?.id || "",
                    taxRateId: defaultGstTax?.id || "",
                    description: "",
                  });
                  setRuleModalOpen(true);
                }}
              >
                <Plus size={15} /> Create rule
              </button>
            )}
          </div>
        </div>
        <main className="x-main">
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr>
                  <th>Rule Name</th>
                  <th>Type</th>
                  <th>Conditions</th>
                  <th>Allocations (100%)</th>
                  <th style={{ width: 140 }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {bankRules.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 600 }}>{r.name}</td>
                    <td>
                      <span className={`x-badge ${r.ruleType === "RECEIVE" ? "green" : "blue"}`}>{r.ruleType}</span>
                    </td>
                    <td>
                      {r.matchStrategy}:{" "}
                      {r.conditions.map((c, i) => (
                        <span key={i} className="x-badge" style={{ marginRight: 4 }}>
                          {c.field} {c.operator} "{c.value}"
                        </span>
                      ))}
                    </td>
                    <td>
                      {r.percentLines.map((pl, idx) => {
                        const acc = accounts.find((a) => a.id === pl.accountId);
                        return (
                          <div key={idx}>
                            {pl.percent}% → {acc ? `${acc.code || ""} ${acc.name}` : pl.accountId}
                          </div>
                        );
                      })}
                    </td>
                    <td>
                      {canWrite && (
                        <button className="x-btn x-btn-danger x-btn-sm" onClick={() => handleDeleteRule(r.id)}>
                          <Trash2 size={13} /> Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {bankRules.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ textAlign: "center", padding: 28, color: "var(--xui-ink-muted)" }}>
                      No bank rules configured yet. Create a rule to automate recurring bank feeds.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </main>
        {ruleModalOpen && renderRuleModal()}
      </>
    );
  }

  // --- BANK ACCOUNTS OVERVIEW ---
  if (route === "bank-accounts") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Accounting &gt; Bank accounts</div>
            <h1 className="x-page-title">Bank Accounts</h1>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="x-btn" onClick={() => onNavigate("bank-rules")}>
              <Sliders size={14} /> Bank Rules
            </button>
            {canWrite && (
              <button className="x-btn x-btn-primary" onClick={() => setAddBankOpen(true)}>
                <Plus size={15} /> Add Bank Account
              </button>
            )}
          </div>
        </div>
        <main className="x-main">
          <div className="x-grid-2">
            {bankAccounts.map((b) => {
              const diffNum = parseFloat(b.difference);
              return (
                <div key={b.id} className="x-card">
                  <div className="x-card-header">
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 16 }}>{b.name}</div>
                      <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>
                        {b.bankAccountNumber || `Code ${b.code || "-"}`} • {b.currency}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      {canWrite && (
                        <button
                          className="x-btn x-btn-sm"
                          onClick={() => {
                            onSelectBankId(b.id);
                            setCsvModalOpen(true);
                          }}
                        >
                          <Upload size={13} /> Import CSV
                        </button>
                      )}
                      {b.unreconciledCount > 0 ? (
                        <button
                          className="x-btn x-btn-primary x-btn-sm"
                          onClick={() => {
                            onSelectBankId(b.id);
                            onNavigate("bank-reconcile");
                          }}
                        >
                          Reconcile {b.unreconciledCount} items
                        </button>
                      ) : (
                        <button
                          className="x-btn x-btn-sm"
                          onClick={() => {
                            onSelectBankId(b.id);
                            onNavigate("bank-reconcile");
                          }}
                        >
                          Open Workbench
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="x-card-body">
                    <div className="x-grid-3">
                      <div>
                        <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>Statement Balance</div>
                        <div style={{ fontSize: 19, fontWeight: 700 }}>{fmtAud(b.statementBalance)}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>Balance in Xero</div>
                        <div style={{ fontSize: 19, fontWeight: 700 }}>{fmtAud(b.bookBalance)}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>Difference</div>
                        <div
                          style={{
                            fontSize: 16,
                            fontWeight: 700,
                            color: Math.abs(diffNum) < 0.005 ? "var(--xui-green)" : "var(--xui-amber)",
                          }}
                        >
                          {fmtAud(b.difference)}
                        </div>
                      </div>
                    </div>
                    <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        className="x-btn x-btn-sm"
                        onClick={() => {
                          onSelectBankId(b.id);
                          setSubTab("cashcoding");
                          onNavigate("cash-coding");
                        }}
                      >
                        <FileSpreadsheet size={13} /> Cash Coding
                      </button>
                      <button
                        className="x-btn x-btn-sm"
                        onClick={() => {
                          onSelectBankId(b.id);
                          setSubTab("statements");
                          onNavigate("bank-reconcile");
                        }}
                      >
                        Bank Statements
                      </button>
                      <button
                        className="x-btn x-btn-sm"
                        onClick={() => {
                          onSelectBankId(b.id);
                          setSubTab("transactions");
                          onNavigate("bank-reconcile");
                        }}
                      >
                        Account Transactions
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </main>
        {csvModalOpen && renderCsvModal()}
        {addBankOpen && renderAddBankModal()}
      </>
    );
  }

  // --- RECONCILE & CASH CODING WORKBENCH ---
  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Accounting &gt; Bank accounts &gt; {activeBank?.name || "Bank"}</div>
          <h1 className="x-page-title">
            <select
              className="x-select"
              style={{ width: "auto", fontWeight: 700, fontSize: 16 }}
              value={activeBank?.id || ""}
              onChange={(e) => onSelectBankId(e.target.value)}
            >
              {bankAccounts.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.unreconciledCount} to reconcile)
                </option>
              ))}
            </select>
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", gap: 18, marginRight: 14, fontSize: 12.5 }}>
            <div>
              <div style={{ color: "var(--xui-ink-muted)" }}>Statement balance</div>
              <strong className="num">{fmtAud(activeBank?.statementBalance)}</strong>
            </div>
            <div>
              <div style={{ color: "var(--xui-ink-muted)" }}>Balance in Xero</div>
              <strong className="num">{fmtAud(activeBank?.bookBalance)}</strong>
            </div>
            <div>
              <div style={{ color: "var(--xui-ink-muted)" }}>Difference</div>
              <strong
                className="num"
                style={{
                  color: Math.abs(parseFloat(activeBank?.difference || "0")) < 0.005 ? "var(--xui-green)" : "var(--xui-amber)",
                }}
              >
                {fmtAud(activeBank?.difference)}
              </strong>
            </div>
          </div>
          {canWrite && (
            <button className="x-btn" onClick={() => setCsvModalOpen(true)}>
              <Upload size={14} /> Import Statement (CSV)
            </button>
          )}
          <button className="x-btn" onClick={() => activeBank && loadBankDetails(activeBank.id)}>
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      <main className="x-main">
        <div className="x-tabs">
          <button
            className={`x-tab ${subTab === "reconcile" ? "active" : ""}`}
            onClick={() => setSubTab("reconcile")}
          >
            Reconcile ({suggestions?.statementLines.length ?? 0})
          </button>
          <button
            className={`x-tab ${subTab === "cashcoding" ? "active" : ""}`}
            onClick={() => setSubTab("cashcoding")}
          >
            Cash coding ({suggestions?.statementLines.length ?? 0})
          </button>
          <button
            className={`x-tab ${subTab === "statements" ? "active" : ""}`}
            onClick={() => setSubTab("statements")}
          >
            Bank statements ({statementAll.length})
          </button>
          <button
            className={`x-tab ${subTab === "transactions" ? "active" : ""}`}
            onClick={() => setSubTab("transactions")}
          >
            Bank transactions ({bankTxs.length})
          </button>
        </div>

        {loading && <div className="x-alert info">Loading bank feed and matching suggestions...</div>}

        {subTab === "reconcile" && (
          <>
            {suggestions?.statementLines.length === 0 ? (
              <div className="x-card">
                <div className="x-card-body" style={{ textAlign: "center", padding: 36 }}>
                  <Check size={28} color="var(--xui-green)" />
                  <h3 style={{ margin: "8px 0 4px" }}>All statement lines reconciled!</h3>
                  <p style={{ color: "var(--xui-ink-muted)", marginBottom: 14 }}>
                    Import a CSV statement or inspect existing Bank statements to unreconcile or Remove & Redo.
                  </p>
                  {canWrite && (
                    <button className="x-btn x-btn-primary" onClick={() => setCsvModalOpen(true)}>
                      <Upload size={14} /> Import CSV Statement
                    </button>
                  )}
                </div>
              </div>
            ) : (
              suggestions?.statementLines.map((line) => {
                const amt = parseFloat(line.amount);
                const isSpent = amt < 0;
                const activePaneTab =
                  lineTab[line.id] ||
                  (line.suggestionType === "MATCH_EXISTING_PAYMENT" || line.suggestionType === "MATCH_INVOICE"
                    ? "match"
                    : "create");
                const draft = getDraft(line);
                const sel = matchSelections[line.id] || { invoiceIds: [], adjAmount: "0.00", adjAccountId: "" };

                return (
                  <div key={line.id} className={`x-rec-row ${line.suggestionType !== "NONE" ? "matched" : ""}`}>
                    {/* LEFT: Bank Statement Line */}
                    <div className="x-rec-left">
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                        <span style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{line.txDate}</span>
                        <span className={`x-badge ${isSpent ? "red" : "green"}`}>
                          {isSpent ? `Spent ${fmtAud(line.spent)}` : `Received ${fmtAud(line.received)}`}
                        </span>
                      </div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>{line.payee || "(No payee)"}</div>
                      <div style={{ fontSize: 12.5, color: "var(--xui-ink-muted)", marginTop: 2 }}>
                        {line.description || "-"}
                      </div>
                      {line.reference && (
                        <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)", marginTop: 4 }}>
                          Ref: <strong>{line.reference}</strong>
                        </div>
                      )}
                    </div>

                    {/* MIDDLE: Green OK Button */}
                    <div className="x-rec-mid">
                      <button
                        className={`x-ok-btn ${!canWrite ? "disabled" : ""}`}
                        disabled={!canWrite}
                        title={
                          line.suggestionType !== "NONE"
                            ? "Accept suggested match / rule and reconcile"
                            : "Create & Reconcile using details on the right"
                        }
                        onClick={() => handleOkSuggestion(line)}
                      >
                        OK
                      </button>
                      <span style={{ fontSize: 11, color: "var(--xui-ink-muted)", marginTop: 5 }}>
                        {line.suggestionType === "BANK_RULE"
                          ? "Rule"
                          : line.suggestionType !== "NONE"
                          ? "Match"
                          : "Create"}
                      </span>
                    </div>

                    {/* RIGHT: Match / Create / Transfer / Discuss */}
                    <div>
                      <div className="x-tabs" style={{ marginBottom: 10 }}>
                        {(["match", "create", "transfer", "discuss"] as const).map((t) => (
                          <button
                            key={t}
                            className={`x-tab ${activePaneTab === t ? "active" : ""}`}
                            style={{ padding: "5px 10px", fontSize: 12 }}
                            onClick={() => setLineTab((prev) => ({ ...prev, [line.id]: t }))}
                          >
                            {t.charAt(0).toUpperCase() + t.slice(1)}
                          </button>
                        ))}
                      </div>

                      {line.suggestionType !== "NONE" && (
                        <div className="x-alert success" style={{ marginBottom: 8, padding: "7px 10px" }}>
                          <div style={{ fontSize: 12.5 }}>
                            {line.suggestionType === "MATCH_EXISTING_PAYMENT" && line.matchedPayment && (
                              <>
                                <strong>Auto-Match Payment:</strong> {line.matchedPayment.invoiceNumber || line.matchedPayment.paymentId} (
                                {fmtAud(line.matchedPayment.amount)})
                              </>
                            )}
                            {line.suggestionType === "MATCH_INVOICE" && line.matchedDocument && (
                              <>
                                <strong>Match Open Document:</strong> {line.matchedDocument.invoiceNumber} —{" "}
                                {line.matchedDocument.contactName} (Due {fmtAud(line.matchedDocument.amountDue)})
                              </>
                            )}
                            {line.suggestionType === "BANK_RULE" && line.matchedRule && (
                              <>
                                <strong>Bank Rule Applied:</strong> {line.matchedRule.ruleName} ({line.matchedRule.ruleType})
                              </>
                            )}
                          </div>
                        </div>
                      )}

                      {activePaneTab === "match" && (
                        <div>
                          <div style={{ maxHeight: 135, overflowY: "auto", border: "1px solid var(--xui-border)", borderRadius: 4 }}>
                            <table className="x-table" style={{ fontSize: 12 }}>
                              <thead>
                                <tr>
                                  <th style={{ width: 28 }}></th>
                                  <th>Doc #</th>
                                  <th>Contact</th>
                                  <th className="num">Due</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(suggestions?.openDocuments || [])
                                  .filter((d) =>
                                    isSpent ? d.invoiceType === "ACCPAY" : d.invoiceType === "ACCREC"
                                  )
                                  .map((d) => {
                                    const checked = sel.invoiceIds.includes(d.id);
                                    return (
                                      <tr key={d.id}>
                                        <td>
                                          <input
                                            type="checkbox"
                                            checked={checked}
                                            onChange={(e) => {
                                              const nextIds = e.target.checked
                                                ? [...sel.invoiceIds, d.id]
                                                : sel.invoiceIds.filter((x) => x !== d.id);
                                              setMatchSelections((p) => ({
                                                ...p,
                                                [line.id]: { ...sel, invoiceIds: nextIds },
                                              }));
                                            }}
                                          />
                                        </td>
                                        <td>{d.invoiceNumber}</td>
                                        <td>{d.contactName}</td>
                                        <td className="num">{fmtAud(d.amountDue)}</td>
                                      </tr>
                                    );
                                  })}
                              </tbody>
                            </table>
                          </div>
                          <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
                            <input
                              className="x-input"
                              style={{ width: 110 }}
                              placeholder="Minor adj $"
                              value={sel.adjAmount}
                              onChange={(e) =>
                                setMatchSelections((p) => ({ ...p, [line.id]: { ...sel, adjAmount: e.target.value } }))
                              }
                            />
                            <select
                              className="x-select"
                              style={{ flex: 1 }}
                              value={sel.adjAccountId || defaultExpenseAcc?.id || ""}
                              onChange={(e) =>
                                setMatchSelections((p) => ({ ...p, [line.id]: { ...sel, adjAccountId: e.target.value } }))
                              }
                            >
                              {nonBankAccounts.map((a) => (
                                <option key={a.id} value={a.id}>
                                  {a.code} {a.name}
                                </option>
                              ))}
                            </select>
                            {canWrite && (
                              <button className="x-btn x-btn-green x-btn-sm" onClick={() => handleMatchManual(line)}>
                                Reconcile Match
                              </button>
                            )}
                          </div>
                        </div>
                      )}

                      {activePaneTab === "create" && (
                        <div className="x-grid-2" style={{ gap: 8 }}>
                          <div className="x-field">
                            <label>Who</label>
                            <select
                              className="x-select"
                              value={draft.contactId}
                              onChange={(e) =>
                                setCreateDrafts((p) => ({ ...p, [line.id]: { ...draft, contactId: e.target.value } }))
                              }
                            >
                              <option value="">-- Optional Contact --</option>
                              {contacts.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="x-field">
                            <label>What (Account)</label>
                            <select
                              className="x-select"
                              value={draft.accountId}
                              onChange={(e) =>
                                setCreateDrafts((p) => ({ ...p, [line.id]: { ...draft, accountId: e.target.value } }))
                              }
                            >
                              {nonBankAccounts.map((a) => (
                                <option key={a.id} value={a.id}>
                                  {a.code ? `${a.code} - ` : ""}
                                  {a.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div className="x-field">
                            <label>Why (Description)</label>
                            <input
                              className="x-input"
                              value={draft.description}
                              onChange={(e) =>
                                setCreateDrafts((p) => ({ ...p, [line.id]: { ...draft, description: e.target.value } }))
                              }
                            />
                          </div>
                          <div className="x-field">
                            <label>Tax Rate</label>
                            <select
                              className="x-select"
                              value={draft.taxRateId}
                              onChange={(e) =>
                                setCreateDrafts((p) => ({ ...p, [line.id]: { ...draft, taxRateId: e.target.value } }))
                              }
                            >
                              {taxRates.map((tr) => (
                                <option key={tr.id} value={tr.id}>
                                  {tr.name} ({tr.ratePercent}%)
                                </option>
                              ))}
                            </select>
                          </div>
                          {track1 && (
                            <div className="x-field">
                              <label>{track1.name}</label>
                              <select
                                className="x-select"
                                value={draft.tracking1OptionId}
                                onChange={(e) =>
                                  setCreateDrafts((p) => ({
                                    ...p,
                                    [line.id]: { ...draft, tracking1OptionId: e.target.value },
                                  }))
                                }
                              >
                                <option value="">-- None --</option>
                                {track1.options.map((o) => (
                                  <option key={o.id} value={o.id}>
                                    {o.name}
                                  </option>
                                ))}
                              </select>
                            </div>
                          )}
                        </div>
                      )}

                      {activePaneTab === "transfer" && (
                        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                          <div className="x-field" style={{ flex: 1 }}>
                            <label>Select other bank account</label>
                            <select
                              className="x-select"
                              value={transferTargets[line.id] || suggestions?.otherBankAccounts?.[0]?.id || ""}
                              onChange={(e) => setTransferTargets((p) => ({ ...p, [line.id]: e.target.value }))}
                            >
                              {(suggestions?.otherBankAccounts || []).map((ob) => (
                                <option key={ob.id} value={ob.id}>
                                  {ob.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          {canWrite && (
                            <button className="x-btn x-btn-green" onClick={() => handleTransfer(line)}>
                              <ArrowLeftRight size={14} /> Post Transfer
                            </button>
                          )}
                        </div>
                      )}

                      {activePaneTab === "discuss" && (
                        <div style={{ fontSize: 12.5, color: "var(--xui-ink-muted)" }}>
                          {line.discussNote || "No internal notes recorded for this feed line."}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </>
        )}

        {subTab === "cashcoding" && (
          <div className="x-card">
            <div className="x-card-header">
              <div className="x-card-title">Cash Coding Spreadsheet (Batch Coding & Reconcile)</div>
              {canWrite && (
                <button className="x-btn x-btn-green" onClick={handleCashCodingApply}>
                  <Check size={15} /> Save & Reconcile Selected (
                  {Object.values(ccSelected).filter(Boolean).length})
                </button>
              )}
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="x-table">
                <thead>
                  <tr>
                    <th style={{ width: 32 }}>
                      <input
                        type="checkbox"
                        onChange={(e) => {
                          const next: Record<string, boolean> = {};
                          for (const l of suggestions?.statementLines || []) next[l.id] = e.target.checked;
                          setCcSelected(next);
                        }}
                      />
                    </th>
                    <th>Date</th>
                    <th>Payee</th>
                    <th>Description</th>
                    <th>Account</th>
                    <th>Tax Rate</th>
                    {track1 && <th>{track1.name}</th>}
                    <th className="num">Spent</th>
                    <th className="num">Received</th>
                  </tr>
                </thead>
                <tbody>
                  {(suggestions?.statementLines || []).map((l) => {
                    const isSpent = parseFloat(l.amount) < 0;
                    const ed = ccEdits[l.id] || {
                      accountId:
                        l.matchedRule?.lines?.[0]?.accountId ||
                        (isSpent ? defaultExpenseAcc?.id : defaultIncomeAcc?.id) ||
                        "",
                      taxRateId:
                        l.matchedRule?.lines?.[0]?.taxRateId ||
                        (isSpent
                          ? taxRates.find((t) => t.code === "INPUT")?.id
                          : taxRates.find((t) => t.code === "OUTPUT")?.id) ||
                        defaultGstTax?.id ||
                        "",
                      description: l.description || l.payee || "",
                      tracking1OptionId: "",
                    };
                    return (
                      <tr key={l.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={!!ccSelected[l.id]}
                            onChange={(e) => setCcSelected((p) => ({ ...p, [l.id]: e.target.checked }))}
                          />
                        </td>
                        <td>{l.txDate}</td>
                        <td>{l.payee || "-"}</td>
                        <td>
                          <input
                            className="x-input"
                            value={ed.description}
                            onChange={(e) =>
                              setCcEdits((p) => ({ ...p, [l.id]: { ...ed, description: e.target.value } }))
                            }
                          />
                        </td>
                        <td>
                          <select
                            className="x-select"
                            value={ed.accountId}
                            onChange={(e) =>
                              setCcEdits((p) => ({ ...p, [l.id]: { ...ed, accountId: e.target.value } }))
                            }
                          >
                            {nonBankAccounts.map((a) => (
                              <option key={a.id} value={a.id}>
                                {a.code} {a.name}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <select
                            className="x-select"
                            value={ed.taxRateId}
                            onChange={(e) =>
                              setCcEdits((p) => ({ ...p, [l.id]: { ...ed, taxRateId: e.target.value } }))
                            }
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
                              value={ed.tracking1OptionId}
                              onChange={(e) =>
                                setCcEdits((p) => ({
                                  ...p,
                                  [l.id]: { ...ed, tracking1OptionId: e.target.value },
                                }))
                              }
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
                        <td className="num">{l.spent ? fmtAud(l.spent) : ""}</td>
                        <td className="num">{l.received ? fmtAud(l.received) : ""}</td>
                      </tr>
                    );
                  })}
                  {(suggestions?.statementLines || []).length === 0 && (
                    <tr>
                      <td colSpan={track1 ? 9 : 8} style={{ textAlign: "center", padding: 28, color: "var(--xui-ink-muted)" }}>
                        No unreconciled statement lines to cash code.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {subTab === "statements" && (
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Payee</th>
                  <th>Description</th>
                  <th>Occ#</th>
                  <th className="num">Amount</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {statementAll.map((s) => (
                  <tr key={s.id}>
                    <td>{s.txDate}</td>
                    <td>{s.payee || "-"}</td>
                    <td>{s.description || "-"}</td>
                    <td>#{s.occurrenceIdx}</td>
                    <td className="num">{fmtAud(s.amount)}</td>
                    <td>
                      <span
                        className={`x-badge ${
                          s.reconcileStatus === "RECONCILED" ? "green" : s.reconcileStatus === "UNRECONCILED" ? "amber" : "red"
                        }`}
                      >
                        {s.reconcileStatus}
                      </span>
                    </td>
                    <td>
                      {s.reconcileStatus === "RECONCILED" && canWrite && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="x-btn x-btn-sm" onClick={() => handleUnreconcile(s.id)}>
                            <Undo2 size={13} /> Unreconcile
                          </button>
                          <button className="x-btn x-btn-danger x-btn-sm" onClick={() => handleRemoveAndRedo(s.id)}>
                            Remove & Redo
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {subTab === "transactions" && (
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type</th>
                  <th>Contact</th>
                  <th>Reference</th>
                  <th>Reconciled</th>
                  <th>Journal #</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {bankTxs.map((tx) => (
                  <tr key={tx.id}>
                    <td>{tx.txDate}</td>
                    <td>
                      <span className="x-badge blue">{tx.txType}</span>
                    </td>
                    <td>{tx.contactName || "-"}</td>
                    <td>{tx.reference || "-"}</td>
                    <td>
                      <span className={`x-badge ${tx.isReconciled ? "green" : "amber"}`}>
                        {tx.isReconciled ? "Reconciled" : "Unreconciled"}
                      </span>
                    </td>
                    <td>{tx.journalNumber ? `#${tx.journalNumber}` : "-"}</td>
                    <td className="num" style={{ fontWeight: 700 }}>
                      {fmtAud(tx.total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {csvModalOpen && renderCsvModal()}
      {addBankOpen && renderAddBankModal()}
      {ruleModalOpen && renderRuleModal()}
    </>
  );

  function renderCsvModal() {
    return (
      <div className="x-modal-backdrop" onClick={() => setCsvModalOpen(false)}>
        <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
          <div className="x-modal-head">
            <h3 style={{ margin: 0 }}>Import CSV Bank Statement — {activeBank?.name}</h3>
            <button className="x-btn x-btn-sm" onClick={() => setCsvModalOpen(false)}>
              Close
            </button>
          </div>
          <div className="x-modal-body">
            <p style={{ fontSize: 12.5, color: "var(--xui-ink-muted)", marginTop: 0 }}>
              Paste CSV rows (Date,Amount,Payee,Description,Reference). Repeated identical lines are tracked by{" "}
              <code>occurrence_idx</code> so double-clicks cannot duplicate imports.
            </p>
            <textarea
              className="x-textarea"
              rows={8}
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
            />
          </div>
          <div className="x-modal-foot">
            <button className="x-btn" onClick={() => setCsvModalOpen(false)}>
              Cancel
            </button>
            <button className="x-btn x-btn-primary" onClick={handleImportCsv}>
              <Upload size={14} /> Import Statement Lines
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderAddBankModal() {
    return (
      <div className="x-modal-backdrop" onClick={() => setAddBankOpen(false)}>
        <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
          <div className="x-modal-head">
            <h3 style={{ margin: 0 }}>Add Bank Account</h3>
            <button className="x-btn x-btn-sm" onClick={() => setAddBankOpen(false)}>
              Close
            </button>
          </div>
          <div className="x-modal-body" style={{ display: "grid", gap: 12 }}>
            <div className="x-field">
              <label>Account Name</label>
              <input className="x-input" value={newBankName} onChange={(e) => setNewBankName(e.target.value)} placeholder="e.g. ANZ Everyday" />
            </div>
            <div className="x-field">
              <label>Account Code</label>
              <input className="x-input" value={newBankCode} onChange={(e) => setNewBankCode(e.target.value)} />
            </div>
            <div className="x-field">
              <label>BSB / Account Number</label>
              <input className="x-input" value={newBankBsb} onChange={(e) => setNewBankBsb(e.target.value)} placeholder="012-345 987654321" />
            </div>
          </div>
          <div className="x-modal-foot">
            <button className="x-btn" onClick={() => setAddBankOpen(false)}>
              Cancel
            </button>
            <button className="x-btn x-btn-primary" onClick={handleAddBankAccount}>
              Save Bank Account
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderRuleModal() {
    return (
      <div className="x-modal-backdrop" onClick={() => setRuleModalOpen(false)}>
        <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
          <div className="x-modal-head">
            <h3 style={{ margin: 0 }}>Create Bank Rule</h3>
            <button className="x-btn x-btn-sm" onClick={() => setRuleModalOpen(false)}>
              Close
            </button>
          </div>
          <div className="x-modal-body" style={{ display: "grid", gap: 10 }}>
            <div className="x-grid-2">
              <div className="x-field">
                <label>Rule Title</label>
                <input className="x-input" value={ruleForm.name} onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })} />
              </div>
              <div className="x-field">
                <label>Money Type</label>
                <select
                  className="x-select"
                  value={ruleForm.ruleType}
                  onChange={(e) => setRuleForm({ ...ruleForm, ruleType: e.target.value as "SPEND" | "RECEIVE" | "TRANSFER" })}
                >
                  <option value="SPEND">Spend Money</option>
                  <option value="RECEIVE">Receive Money</option>
                  <option value="TRANSFER">Transfer</option>
                </select>
              </div>
            </div>
            <div className="x-grid-3">
              <div className="x-field">
                <label>Condition Field</label>
                <select className="x-select" value={ruleForm.field} onChange={(e) => setRuleForm({ ...ruleForm, field: e.target.value })}>
                  <option value="PAYEE">Payee</option>
                  <option value="DESCRIPTION">Description</option>
                  <option value="REFERENCE">Reference</option>
                </select>
              </div>
              <div className="x-field">
                <label>Operator</label>
                <select className="x-select" value={ruleForm.operator} onChange={(e) => setRuleForm({ ...ruleForm, operator: e.target.value })}>
                  <option value="CONTAINS">Contains</option>
                  <option value="EQUALS">Equals</option>
                  <option value="STARTS_WITH">Starts with</option>
                </select>
              </div>
              <div className="x-field">
                <label>Match Value</label>
                <input className="x-input" value={ruleForm.value} onChange={(e) => setRuleForm({ ...ruleForm, value: e.target.value })} placeholder="e.g. Telstra" />
              </div>
            </div>
            <div className="x-grid-2">
              <div className="x-field">
                <label>Allocate to Account (100%)</label>
                <select className="x-select" value={ruleForm.accountId} onChange={(e) => setRuleForm({ ...ruleForm, accountId: e.target.value })}>
                  {nonBankAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.code} {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="x-field">
                <label>Tax Rate</label>
                <select className="x-select" value={ruleForm.taxRateId} onChange={(e) => setRuleForm({ ...ruleForm, taxRateId: e.target.value })}>
                  {taxRates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
          <div className="x-modal-foot">
            <button className="x-btn" onClick={() => setRuleModalOpen(false)}>
              Cancel
            </button>
            <button className="x-btn x-btn-primary" onClick={handleSaveRule}>
              Save Bank Rule
            </button>
          </div>
        </div>
      </div>
    );
  }
}
