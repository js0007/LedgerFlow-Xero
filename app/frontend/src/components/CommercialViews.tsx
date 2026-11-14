import React, { useEffect, useState } from "react";
import { ArrowRightLeft, Ban, Check, CreditCard, Plus, Trash2 } from "lucide-react";
import { api, fmtAud } from "../api";
import type {
  AccountItem,
  BankAccountSummary,
  CommercialLine,
  ContactItem,
  InvoiceDocument,
  OrgSummary,
  ProductItem,
  TaxRateItem,
  TrackingCategory,
} from "../types";
import type { RouteKey } from "./TopNav";

interface CommercialProps {
  org: OrgSummary;
  mode: "sales-overview" | "invoices" | "quotes" | "purchases-overview" | "bills" | "purchase-orders";
  accounts: AccountItem[];
  taxRates: TaxRateItem[];
  contacts: ContactItem[];
  products: ProductItem[];
  banks: BankAccountSummary[];
  tracking: TrackingCategory[];
  externalCreateKind?: "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "QUOTE" | "PO" | null;
  onClearExternalCreate: () => void;
  onNotify: (kind: "success" | "error" | "info", msg: string) => void;
  onNavigate: (r: RouteKey) => void;
  onDataChanged: () => Promise<void>;
}

const emptyLine = (defAccId: string, defTaxId: string): CommercialLine => ({
  productId: null,
  description: "",
  quantity: "1",
  unitAmount: "0.00",
  discountPct: "0",
  accountId: defAccId,
  taxRateId: defTaxId,
  tracking1OptionId: null,
});

function estimateLine(line: CommercialLine, taxMode: string, rates: TaxRateItem[]) {
  const q = Number(line.quantity || 0);
  const u = Number(line.unitAmount || 0);
  const d = Number(line.discountPct || 0);
  const raw = q * u * (1 - d / 100);
  const tr = rates.find((r) => r.id === line.taxRateId);
  const rate = tr ? Number(tr.rateDecimal) : 0;
  if (taxMode === "NO_TAX" || rate === 0) return { net: raw, tax: 0, gross: raw };
  if (taxMode === "INCLUSIVE") {
    const tax = (raw * rate) / (1 + rate);
    return { net: raw - tax, tax, gross: raw };
  }
  const tax = raw * rate;
  return { net: raw, tax, gross: raw + tax };
}

export const CommercialViews: React.FC<CommercialProps> = ({
  org,
  mode,
  accounts,
  taxRates,
  contacts,
  products,
  banks,
  tracking,
  externalCreateKind,
  onClearExternalCreate,
  onNotify,
  onNavigate,
  onDataChanged,
}) => {
  const [docs, setDocs] = useState<InvoiceDocument[]>([]);
  const [quotes, setQuotes] = useState<any[]>([]);
  const [pos, setPos] = useState<any[]>([]);
  const [statusTab, setStatusTab] = useState<string>("ALL");
  const [loading, setLoading] = useState(false);

  // Editor modal state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editKind, setEditKind] = useState<"ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "ACCPAYCREDIT" | "QUOTE" | "PO">("ACCREC");
  const [editingDoc, setEditingDoc] = useState<InvoiceDocument | null>(null);
  const [editingQuoteOrPo, setEditingQuoteOrPo] = useState<{ kind: "QUOTE" | "PO"; id: string; docNumber: string; status: string } | null>(null);
  const [editUnlocked, setEditUnlocked] = useState(false);
  const [contactId, setContactId] = useState("");
  const [docNumber, setDocNumber] = useState("");
  const [reference, setReference] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = useState(new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10));
  const [taxMode, setTaxMode] = useState<"EXCLUSIVE" | "INCLUSIVE" | "NO_TAX">("EXCLUSIVE");
  const [lines, setLines] = useState<CommercialLine[]>([]);

  // Payment & Credit allocation sub-panels inside authorised document view
  const [payAmount, setPayAmount] = useState("");
  const [payDate, setPayDate] = useState(new Date().toISOString().slice(0, 10));
  const [payBankId, setPayBankId] = useState("");
  const [payRef, setPayRef] = useState("");
  const [allocOpen, setAllocOpen] = useState(false);
  const [allocTargets, setAllocTargets] = useState<InvoiceDocument[]>([]);
  const [allocMap, setAllocMap] = useState<Record<string, string>>({});

  const readOnly = org.role === "READONLY";
  const isSalesSection = mode === "sales-overview" || mode === "invoices" || mode === "quotes";
  const defaultSalesAcc = accounts.find((a) => a.code === "200")?.id || accounts[0]?.id || "";
  const defaultPurchAcc = accounts.find((a) => a.code === "453")?.id || accounts[0]?.id || "";
  const defaultOutTax = taxRates.find((t) => t.code === "OUTPUT")?.id || taxRates[0]?.id || "";
  const defaultInTax = taxRates.find((t) => t.code === "INPUT")?.id || taxRates[0]?.id || "";
  const regionOptions = tracking[0]?.options || [];

  const loadData = async () => {
    setLoading(true);
    try {
      const [invList, qList, pList] = await Promise.all([
        api.get<InvoiceDocument[]>(`/orgs/${org.id}/invoices?invoiceType=${isSalesSection ? "ACCREC,ACCRECCREDIT" : "ACCPAY,ACCPAYCREDIT"}`),
        api.get<any[]>(`/orgs/${org.id}/quotes`),
        api.get<any[]>(`/orgs/${org.id}/purchase-orders`),
      ]);
      setDocs(invList);
      setQuotes(qList);
      setPos(pList);
    } catch (e: any) {
      onNotify("error", e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [org.id, mode]);

  const openNewEditor = (kind: "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "ACCPAYCREDIT" | "QUOTE" | "PO") => {
    setEditingDoc(null);
    setEditingQuoteOrPo(null);
    setEditUnlocked(false);
    setEditKind(kind);
    const isPay = kind === "ACCPAY" || kind === "ACCPAYCREDIT" || kind === "PO";
    setTaxMode(isPay ? "INCLUSIVE" : "EXCLUSIVE");
    const firstContact = contacts.find((c) => (isPay ? c.isSupplier : c.isCustomer)) || contacts[0];
    setContactId(firstContact?.id || "");
    setDocNumber("");
    setReference("");
    const today = new Date().toISOString().slice(0, 10);
    setIssueDate(today);
    setDueDate(new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10));
    setLines([emptyLine(isPay ? defaultPurchAcc : defaultSalesAcc, isPay ? defaultInTax : defaultOutTax)]);
    setEditorOpen(true);
  };

  useEffect(() => {
    if (externalCreateKind) {
      openNewEditor(externalCreateKind);
      onClearExternalCreate();
    }
  }, [externalCreateKind]);

  const openExistingQuoteOrPo = (kind: "QUOTE" | "PO", doc: any) => {
    setEditingDoc(null);
    setEditingQuoteOrPo({
      kind,
      id: doc.id,
      docNumber: kind === "QUOTE" ? doc.quoteNumber : doc.poNumber,
      status: doc.status,
    });
    setEditUnlocked(false);
    setEditKind(kind);
    setContactId(doc.contactId || doc.contact_id || "");
    setDocNumber(kind === "QUOTE" ? doc.quoteNumber : doc.poNumber);
    setReference(doc.reference || "");
    setIssueDate(doc.issueDate);
    setDueDate((kind === "QUOTE" ? doc.expiryDate : doc.deliveryDate) || doc.issueDate);
    setTaxMode(doc.taxMode || (kind === "PO" ? "INCLUSIVE" : "EXCLUSIVE"));
    setLines((doc.lines || []).map((l: any) => ({ ...l })));
    setAllocOpen(false);
    setEditorOpen(true);
  };

  const openExistingDoc = async (doc: InvoiceDocument) => {
    try {
      const fresh = await api.get<InvoiceDocument>(`/orgs/${org.id}/invoices/${doc.id}`);
      setEditingQuoteOrPo(null);
      setEditingDoc(fresh);
      setEditUnlocked(false);
      setEditKind(fresh.invoiceType);
      setContactId(fresh.contactId);
      setDocNumber(fresh.invoiceNumber);
      setReference(fresh.reference || "");
      setIssueDate(fresh.issueDate);
      setDueDate(fresh.dueDate);
      setTaxMode(fresh.taxMode);
      setLines(fresh.lines.map((l) => ({ ...l })));
      setPayAmount(fresh.amountDue);
      setPayDate(new Date().toISOString().slice(0, 10));
      setPayBankId(banks[0]?.id || "");
      setPayRef("");
      setAllocOpen(false);
      setEditorOpen(true);
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleSaveDoc = async (approveImmediately: boolean) => {
    try {
      if (!contactId) throw new Error("Select a customer or supplier first.");
      if (editingQuoteOrPo?.kind === "QUOTE") {
        await api.patch(`/orgs/${org.id}/quotes/${editingQuoteOrPo.id}`, {
          contactId, reference, issueDate, expiryDate: dueDate, taxMode, lines, title: reference || "Sales Quote",
        });
        onNotify("success", `Updated ${editingQuoteOrPo.docNumber}.`);
      } else if (editingQuoteOrPo?.kind === "PO") {
        await api.patch(`/orgs/${org.id}/purchase-orders/${editingQuoteOrPo.id}`, {
          contactId, reference, issueDate, deliveryDate: dueDate, taxMode, lines,
        });
        onNotify("success", `Updated ${editingQuoteOrPo.docNumber}.`);
      } else if (editKind === "QUOTE") {
        await api.post(`/orgs/${org.id}/quotes`, { contactId, reference, issueDate, expiryDate: dueDate, taxMode, lines, title: reference || "Sales Quote" });
        onNotify("success", "Quote saved cleanly (zero GL impact until invoiced).");
      } else if (editKind === "PO") {
        await api.post(`/orgs/${org.id}/purchase-orders`, { contactId, reference, issueDate, deliveryDate: dueDate, taxMode, lines });
        onNotify("success", "Purchase Order saved.");
      } else if (editingDoc && (editingDoc.status === "DRAFT" || editingDoc.status === "SUBMITTED")) {
        await api.patch(`/orgs/${org.id}/invoices/${editingDoc.id}`, {
          contactId, invoiceNumber: docNumber || undefined, reference, issueDate, dueDate, taxMode, lines, version: editingDoc.version,
        });
        if (approveImmediately) {
          await api.post(`/orgs/${org.id}/invoices/${editingDoc.id}/approve`);
          onNotify("success", `${editingDoc.invoiceNumber} approved and posted to GL.`);
        } else {
          onNotify("success", "Draft updated.");
        }
      } else if (editingDoc && editingDoc.status === "AUTHORISED") {
        await api.patch(`/orgs/${org.id}/invoices/${editingDoc.id}`, {
          contactId, invoiceNumber: docNumber || undefined, reference, issueDate, dueDate, taxMode, lines, version: editingDoc.version,
        });
        onNotify("success", `${editingDoc.invoiceNumber} updated with reversal & reposted GL journal.`);
      } else {
        const res = await api.post<InvoiceDocument>(`/orgs/${org.id}/invoices`, {
          invoiceType: editKind,
          contactId,
          invoiceNumber: docNumber || undefined,
          reference,
          issueDate,
          dueDate,
          taxMode,
          lines,
          approveImmediately,
        });
        onNotify("success", approveImmediately ? `${res.invoiceNumber} approved & posted to General Ledger.` : `${res.invoiceNumber} saved as Draft.`);
      }
      setEditorOpen(false);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleDeleteInvoice = async (doc: InvoiceDocument) => {
    try {
      await api.del(`/orgs/${org.id}/invoices/${doc.id}`);
      onNotify("info", `Deleted draft ${doc.invoiceNumber}.`);
      setEditorOpen(false);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleDeallocate = async (allocId: string) => {
    if (!editingDoc) return;
    try {
      await api.del(`/orgs/${org.id}/credit-note-allocations/${allocId}`);
      onNotify("info", "Credit allocation reversed and balances reopened.");
      await openExistingDoc(editingDoc);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleQuoteStatus = async (qId: string, qNumber: string, status: string) => {
    try {
      await api.patch(`/orgs/${org.id}/quotes/${qId}`, { status });
      onNotify("success", `${qNumber} marked ${status}.`);
      await loadData();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleDeleteQuote = async (qId: string, qNumber: string) => {
    try {
      await api.del(`/orgs/${org.id}/quotes/${qId}`);
      onNotify("info", `Deleted quote ${qNumber}.`);
      setEditorOpen(false);
      await loadData();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handlePoStatus = async (pId: string, poNumber: string, status: string) => {
    try {
      await api.patch(`/orgs/${org.id}/purchase-orders/${pId}`, { status });
      onNotify("success", `${poNumber} marked ${status}.`);
      await loadData();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleDeletePo = async (pId: string, poNumber: string) => {
    try {
      await api.del(`/orgs/${org.id}/purchase-orders/${pId}`);
      onNotify("info", `Deleted purchase order ${poNumber}.`);
      setEditorOpen(false);
      await loadData();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleApproveExisting = async () => {
    if (!editingDoc) return;
    try {
      const updated = await api.post<InvoiceDocument>(`/orgs/${org.id}/invoices/${editingDoc.id}/approve`);
      onNotify("success", `${updated.invoiceNumber} approved (Journal #${updated.postedJournalNumber}).`);
      setEditingDoc(updated);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleVoidExisting = async () => {
    if (!editingDoc) return;
    try {
      const updated = await api.post<InvoiceDocument>(`/orgs/${org.id}/invoices/${editingDoc.id}/void`);
      onNotify("info", `${updated.invoiceNumber} voided with full GL reversal journal.`);
      setEditingDoc(updated);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleRecordPayment = async () => {
    if (!editingDoc) return;
    try {
      await api.post(`/orgs/${org.id}/payments`, {
        invoiceId: editingDoc.id,
        bankAccountId: payBankId,
        paymentDate: payDate,
        amount: payAmount,
        reference: payRef,
      });
      onNotify("success", `Payment of $${payAmount} recorded cleanly.`);
      await openExistingDoc(editingDoc);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const handleDeletePayment = async (paymentId: string) => {
    if (!editingDoc) return;
    try {
      await api.del(`/orgs/${org.id}/payments/${paymentId}`);
      onNotify("info", "Payment removed and reversal journal posted.");
      await openExistingDoc(editingDoc);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const openCreditAllocation = async () => {
    if (!editingDoc) return;
    const targetType = editingDoc.invoiceType === "ACCRECCREDIT" ? "ACCREC" : "ACCPAY";
    const candidates = docs.filter((d) => d.invoiceType === targetType && d.contactId === editingDoc.contactId && d.status === "AUTHORISED" && Number(d.amountDue) > 0);
    setAllocTargets(candidates);
    const initial: Record<string, string> = {};
    if (candidates[0]) {
      const maxAlloc = Math.min(Number(editingDoc.amountDue), Number(candidates[0].amountDue));
      initial[candidates[0].id] = maxAlloc.toFixed(2);
    }
    setAllocMap(initial);
    setAllocOpen(true);
  };

  const handleSubmitAllocation = async () => {
    if (!editingDoc) return;
    try {
      const allocations = Object.entries(allocMap)
        .filter(([, amt]) => Number(amt) > 0)
        .map(([targetInvoiceId, amount]) => ({ targetInvoiceId, amount }));
      await api.post(`/orgs/${org.id}/invoices/${editingDoc.id}/allocate`, {
        allocationDate: new Date().toISOString().slice(0, 10),
        allocations,
      });
      onNotify("success", `Credit allocated cleanly from ${editingDoc.invoiceNumber}.`);
      setAllocOpen(false);
      await openExistingDoc(editingDoc);
      await loadData();
      await onDataChanged();
    } catch (e: any) {
      onNotify("error", e.message);
    }
  };

  const estTotals = lines.reduce(
    (acc, l) => {
      const x = estimateLine(l, taxMode, taxRates);
      return { net: acc.net + x.net, tax: acc.tax + x.tax, gross: acc.gross + x.gross };
    },
    { net: 0, tax: 0, gross: 0 }
  );

  const filteredDocs = docs.filter((d) => (statusTab === "ALL" ? true : d.status === statusTab));
  const titleText =
    mode === "sales-overview" ? "Sales Overview"
    : mode === "invoices" ? "Invoices & Sales Credit Notes"
    : mode === "quotes" ? "Sales Quotes"
    : mode === "purchases-overview" ? "Purchases Overview"
    : mode === "bills" ? "Bills to Pay & Supplier Credit Notes"
    : "Purchase Orders";

  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Business &bull; {isSalesSection ? "Sales" : "Purchases"}</div>
          <h1 className="x-page-title">{titleText}</h1>
        </div>
        {!readOnly && (
          <div style={{ display: "flex", gap: 8 }}>
            {isSalesSection ? (
              <>
                <button className="x-btn" onClick={() => openNewEditor("QUOTE")}>+ New Quote</button>
                <button className="x-btn" onClick={() => openNewEditor("ACCRECCREDIT")}>+ Credit Note</button>
                <button className="x-btn x-btn-primary" onClick={() => openNewEditor("ACCREC")}><Plus size={14} /> New Invoice</button>
              </>
            ) : (
              <>
                <button className="x-btn" onClick={() => openNewEditor("PO")}>+ New PO</button>
                <button className="x-btn" onClick={() => openNewEditor("ACCPAYCREDIT")}>+ Supplier Credit</button>
                <button className="x-btn x-btn-primary" onClick={() => openNewEditor("ACCPAY")}><Plus size={14} /> New Bill</button>
              </>
            )}
          </div>
        )}
      </div>

      <div className="x-main">
        {/* Overview Funnel Cards when in Overview mode */}
        {(mode === "sales-overview" || mode === "purchases-overview") && (
          <div className="x-grid-4" style={{ marginBottom: 18 }}>
            <div className="x-card clickable" onClick={() => { setStatusTab("DRAFT"); onNavigate(isSalesSection ? "invoices" : "bills"); }}>
              <div className="x-card-body">
                <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Draft ({docs.filter((d) => d.status === "DRAFT").length})</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                  ${fmtAud(docs.filter((d) => d.status === "DRAFT").reduce((s, d) => s + Number(d.total), 0))}
                </div>
              </div>
            </div>
            <div className="x-card">
              <div className="x-card-body">
                <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Awaiting Payment ({docs.filter((d) => d.status === "AUTHORISED").length})</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                  ${fmtAud(docs.filter((d) => d.status === "AUTHORISED").reduce((s, d) => s + Number(d.amountDue), 0))}
                </div>
              </div>
            </div>
            <div className="x-card">
              <div className="x-card-body">
                <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>Paid ({docs.filter((d) => d.status === "PAID").length})</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4, color: "var(--xui-green)" }}>
                  ${fmtAud(docs.filter((d) => d.status === "PAID").reduce((s, d) => s + Number(d.total), 0))}
                </div>
              </div>
            </div>
            <div className="x-card clickable" onClick={() => onNavigate(isSalesSection ? "quotes" : "purchase-orders")}>
              <div className="x-card-body">
                <div style={{ fontSize: 12, color: "var(--xui-ink-muted)" }}>{isSalesSection ? `Quotes (${quotes.length})` : `Purchase Orders (${pos.length})`}</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 700, textAlign: "left", marginTop: 4 }}>
                  ${fmtAud((isSalesSection ? quotes : pos).reduce((s, q) => s + Number(q.total), 0))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Quotes Table */}
        {mode === "quotes" && (
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr><th>Quote #</th><th>Customer</th><th>Title / Ref</th><th>Date</th><th>Expiry</th><th>Status</th><th className="num">Total</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {quotes.map((q) => (
                  <tr key={q.id}>
                    <td><strong>{q.quoteNumber}</strong></td>
                    <td>{q.contactName}</td>
                    <td>{q.title || q.reference || "—"}</td>
                    <td>{q.issueDate}</td>
                    <td>{q.expiryDate || "—"}</td>
                    <td><span className={`x-badge ${q.status === "INVOICED" || q.status === "ACCEPTED" ? "green" : q.status === "DECLINED" ? "red" : "blue"}`}>{q.status}</span></td>
                    <td className="num">${fmtAud(q.total)}</td>
                    <td>
                      {q.status !== "INVOICED" ? (
                        !readOnly && (
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button className="x-btn x-btn-sm" onClick={() => openExistingQuoteOrPo("QUOTE", q)}>Edit</button>
                            {q.status === "DRAFT" && (
                              <button className="x-btn x-btn-sm" onClick={() => handleQuoteStatus(q.id, q.quoteNumber, "SENT")}>Send</button>
                            )}
                            {(q.status === "DRAFT" || q.status === "SENT") && (
                              <button className="x-btn x-btn-sm" onClick={() => handleQuoteStatus(q.id, q.quoteNumber, "ACCEPTED")}>Accept</button>
                            )}
                            {(q.status === "SENT" || q.status === "DRAFT") && (
                              <button className="x-btn x-btn-sm" onClick={() => handleQuoteStatus(q.id, q.quoteNumber, "DECLINED")}>Decline</button>
                            )}
                            <button
                              className="x-btn x-btn-sm x-btn-primary"
                              onClick={async () => {
                                try {
                                  const inv = await api.post<InvoiceDocument>(`/orgs/${org.id}/quotes/${q.id}/convert`, { approve: false });
                                  onNotify("success", `Converted ${q.quoteNumber} → Draft Invoice ${inv.invoiceNumber}.`);
                                  await loadData();
                                  await onDataChanged();
                                } catch (e: any) {
                                  onNotify("error", e.message);
                                }
                              }}
                            >
                              <ArrowRightLeft size={12} /> Copy to Invoice
                            </button>
                            <button className="x-btn x-btn-sm x-btn-danger" onClick={() => handleDeleteQuote(q.id, q.quoteNumber)}>
                              <Trash2 size={12} />
                            </button>
                          </div>
                        )
                      ) : <span style={{ fontSize: 12, color: "var(--xui-green)" }}>Invoiced</span>}
                    </td>
                  </tr>
                ))}
                {quotes.length === 0 && <tr><td colSpan={8} style={{ color: "var(--xui-ink-muted)" }}>No quotes created yet.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {/* Purchase Orders Table */}
        {mode === "purchase-orders" && (
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr><th>PO #</th><th>Supplier</th><th>Reference</th><th>Date</th><th>Delivery</th><th>Status</th><th className="num">Total</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {pos.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.poNumber}</strong></td>
                    <td>{p.contactName}</td>
                    <td>{p.reference || "—"}</td>
                    <td>{p.issueDate}</td>
                    <td>{p.deliveryDate || "—"}</td>
                    <td><span className={`x-badge ${p.status === "BILLED" || p.status === "APPROVED" ? "green" : "blue"}`}>{p.status}</span></td>
                    <td className="num">${fmtAud(p.total)}</td>
                    <td>
                      {p.status !== "BILLED" ? (
                        !readOnly && (
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button className="x-btn x-btn-sm" onClick={() => openExistingQuoteOrPo("PO", p)}>Edit</button>
                            {p.status === "DRAFT" && (
                              <button className="x-btn x-btn-sm" onClick={() => handlePoStatus(p.id, p.poNumber, "AWAITING_APPROVAL")}>Submit</button>
                            )}
                            {(p.status === "DRAFT" || p.status === "AWAITING_APPROVAL") && (
                              <button className="x-btn x-btn-sm" onClick={() => handlePoStatus(p.id, p.poNumber, "APPROVED")}>Approve</button>
                            )}
                            <button
                              className="x-btn x-btn-sm x-btn-primary"
                              onClick={async () => {
                                try {
                                  const bill = await api.post<InvoiceDocument>(`/orgs/${org.id}/purchase-orders/${p.id}/convert`, { approve: false });
                                  onNotify("success", `Copied ${p.poNumber} → Draft Bill ${bill.invoiceNumber}.`);
                                  await loadData();
                                  await onDataChanged();
                                } catch (e: any) {
                                  onNotify("error", e.message);
                                }
                              }}
                            >
                              <ArrowRightLeft size={12} /> Copy to Bill
                            </button>
                            <button className="x-btn x-btn-sm x-btn-danger" onClick={() => handleDeletePo(p.id, p.poNumber)}>
                              <Trash2 size={12} />
                            </button>
                          </div>
                        )
                      ) : <span style={{ fontSize: 12, color: "var(--xui-green)" }}>Billed</span>}
                    </td>
                  </tr>
                ))}
                {pos.length === 0 && <tr><td colSpan={8} style={{ color: "var(--xui-ink-muted)" }}>No purchase orders created yet.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {/* Invoices / Bills / Credit Notes List */}
        {mode !== "quotes" && mode !== "purchase-orders" && (
          <>
            <div className="x-tabs">
              {["ALL", "DRAFT", "AUTHORISED", "PAID", "VOIDED"].map((st) => (
                <button key={st} className={`x-tab ${statusTab === st ? "active" : ""}`} onClick={() => setStatusTab(st)}>
                  {st === "AUTHORISED" ? "Awaiting Payment" : st === "ALL" ? `All (${docs.length})` : `${st[0] + st.slice(1).toLowerCase()} (${docs.filter((d) => d.status === st).length})`}
                </button>
              ))}
            </div>
            <div className="x-card">
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Number</th>
                    <th>Type</th>
                    <th>Reference</th>
                    <th>{isSalesSection ? "To" : "From"}</th>
                    <th>Date</th>
                    <th>Due Date</th>
                    <th className="num">Paid / Credited</th>
                    <th className="num">Due</th>
                    <th className="num">Total</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDocs.map((d) => {
                    const isCredit = d.invoiceType.endsWith("CREDIT");
                    const badgeCls = d.status === "PAID" ? "green" : d.status === "AUTHORISED" ? "blue" : d.status === "VOIDED" ? "red" : "amber";
                    return (
                      <tr key={d.id} className="clickable" onClick={() => openExistingDoc(d)}>
                        <td><strong style={{ color: "var(--xui-nav-blue)" }}>{d.invoiceNumber}</strong></td>
                        <td><span className={`x-badge ${isCredit ? "amber" : ""}`}>{isCredit ? "Credit Note" : d.invoiceType === "ACCREC" ? "Invoice" : "Bill"}</span></td>
                        <td>{d.reference || "—"}</td>
                        <td>{d.contactName}</td>
                        <td>{d.issueDate}</td>
                        <td>{d.dueDate}</td>
                        <td className="num">${fmtAud(Number(d.amountPaid) + Number(d.amountCredited))}</td>
                        <td className="num"><strong>{isCredit ? `(${fmtAud(d.amountDue)})` : `$${fmtAud(d.amountDue)}`}</strong></td>
                        <td className="num">{isCredit ? `(${fmtAud(d.total)})` : `$${fmtAud(d.total)}`}</td>
                        <td><span className={`x-badge ${badgeCls}`}>{d.status === "AUTHORISED" ? "Awaiting Payment" : d.status}</span></td>
                      </tr>
                    );
                  })}
                  {!loading && filteredDocs.length === 0 && (
                    <tr><td colSpan={10} style={{ color: "var(--xui-ink-muted)" }}>No documents in this view.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {/* Document Editor / Inspector Modal */}
      {editorOpen && (
        <div className="x-modal-backdrop" onClick={() => setEditorOpen(false)}>
          <div className="x-modal" onClick={(e) => e.stopPropagation()}>
            <div className="x-modal-head">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <strong style={{ fontSize: 16 }}>
                  {editingDoc
                    ? `${editingDoc.invoiceNumber} (${editingDoc.invoiceType})`
                    : editingQuoteOrPo
                    ? `${editingQuoteOrPo.docNumber} (${editingQuoteOrPo.kind})`
                    : `New ${editKind}`}
                </strong>
                {editingDoc && (
                  <span className={`x-badge ${editingDoc.status === "PAID" ? "green" : editingDoc.status === "VOIDED" ? "red" : "blue"}`}>
                    {editingDoc.status}
                  </span>
                )}
                {editingQuoteOrPo && <span className="x-badge blue">{editingQuoteOrPo.status}</span>}
                {editingDoc?.postedJournalNumber && <span className="x-badge">GL Journal #{editingDoc.postedJournalNumber}</span>}
              </div>
              <button className="x-btn x-btn-sm" onClick={() => setEditorOpen(false)}>Close</button>
            </div>

            <div className="x-modal-body">
              {(() => {
                const docLocked =
                  readOnly ||
                  (editingQuoteOrPo
                    ? editingQuoteOrPo.status === "INVOICED" || editingQuoteOrPo.status === "BILLED"
                    : !!editingDoc &&
                      editingDoc.status !== "DRAFT" &&
                      editingDoc.status !== "SUBMITTED" &&
                      !(editingDoc.status === "AUTHORISED" && editUnlocked));
                return (
                  <>
              <div className="x-grid-4" style={{ marginBottom: 16 }}>
                <div className="x-field">
                  <label>{editKind.startsWith("ACCPAY") || editKind === "PO" ? "Supplier" : "Customer"}</label>
                  <select
                    className="x-select"
                    value={contactId}
                    disabled={docLocked}
                    onChange={(e) => {
                      const cid = e.target.value;
                      setContactId(cid);
                      const c = contacts.find((x) => x.id === cid);
                      if (c && !editingDoc && !editingQuoteOrPo) {
                        const isP = editKind.startsWith("ACCPAY") || editKind === "PO";
                        const defA = isP ? c.defaultPurchaseAccountId : c.defaultSalesAccountId;
                        const defT = isP ? c.defaultPurchaseTaxRateId : c.defaultSalesTaxRateId;
                        if (defA || defT) {
                          setLines((prev) => prev.map((ln) => ({ ...ln, accountId: defA || ln.accountId, taxRateId: defT || ln.taxRateId })));
                        }
                      }
                    }}
                  >
                    <option value="">-- Select Contact --</option>
                    {contacts.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
                <div className="x-field">
                  <label>Issue Date</label>
                  <input className="x-input" type="date" value={issueDate} disabled={docLocked} onChange={(e) => setIssueDate(e.target.value)} />
                </div>
                <div className="x-field">
                  <label>Due / Expiry Date</label>
                  <input className="x-input" type="date" value={dueDate} disabled={docLocked} onChange={(e) => setDueDate(e.target.value)} />
                </div>
                <div className="x-field">
                  <label>Amounts Are (GST Mode)</label>
                  <select className="x-select" value={taxMode} disabled={docLocked} onChange={(e) => setTaxMode(e.target.value as any)}>
                    <option value="EXCLUSIVE">Tax Exclusive</option>
                    <option value="INCLUSIVE">Tax Inclusive</option>
                    <option value="NO_TAX">No Tax</option>
                  </select>
                </div>
              </div>

              <div className="x-grid-2" style={{ marginBottom: 14 }}>
                <div className="x-field">
                  <label>Document Number (Optional auto-sequence)</label>
                  <input className="x-input" value={docNumber} placeholder="Auto-generated if blank (e.g. INV-0001 / CN-0002)" disabled={docLocked || !!editingQuoteOrPo} onChange={(e) => setDocNumber(e.target.value)} />
                </div>
                <div className="x-field">
                  <label>Reference</label>
                  <input className="x-input" value={reference} disabled={docLocked} onChange={(e) => setReference(e.target.value)} placeholder="Customer PO / Ref" />
                </div>
              </div>

              <table className="x-table" style={{ marginBottom: 14 }}>
                <thead>
                  <tr>
                    <th style={{ width: 115 }}>Item</th>
                    <th>Description</th>
                    <th style={{ width: 65 }}>Qty</th>
                    <th style={{ width: 95 }}>Unit Price</th>
                    <th style={{ width: 65 }}>Disc%</th>
                    <th style={{ width: 170 }}>Account</th>
                    <th style={{ width: 145 }}>Tax Rate</th>
                    {regionOptions.length > 0 && <th style={{ width: 110 }}>Region</th>}
                    <th className="num" style={{ width: 95 }}>Amount</th>
                    <th style={{ width: 34 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((ln, i) => {
                    const est = estimateLine(ln, taxMode, taxRates);
                    const locked = docLocked;
                    return (
                      <tr key={i}>
                        <td>
                          <select
                            className="x-select"
                            value={ln.productId || ""}
                            disabled={locked}
                            onChange={(e) => {
                              const p = products.find((x) => x.id === e.target.value);
                              setLines((prev) =>
                                prev.map((row, idx) =>
                                  idx !== i ? row : p
                                    ? {
                                        ...row,
                                        productId: p.id,
                                        description: p.name,
                                        unitAmount: editKind.startsWith("ACCPAY") ? p.costPrice || row.unitAmount : p.salePrice || row.unitAmount,
                                        accountId: (editKind.startsWith("ACCPAY") ? p.purchaseAccountId : p.salesAccountId) || row.accountId,
                                        taxRateId: (editKind.startsWith("ACCPAY") ? p.purchaseTaxRateId : p.salesTaxRateId) || row.taxRateId,
                                      }
                                    : { ...row, productId: null }
                                )
                              );
                            }}
                          >
                            <option value="">Custom</option>
                            {products.map((p) => <option key={p.id} value={p.id}>{p.code}</option>)}
                          </select>
                        </td>
                        <td><input className="x-input" value={ln.description} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, description: e.target.value } : r)))} /></td>
                        <td><input className="x-input num" value={ln.quantity} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, quantity: e.target.value } : r)))} /></td>
                        <td><input className="x-input num" value={ln.unitAmount} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, unitAmount: e.target.value } : r)))} /></td>
                        <td><input className="x-input num" value={ln.discountPct} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, discountPct: e.target.value } : r)))} /></td>
                        <td>
                          <select className="x-select" value={ln.accountId} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, accountId: e.target.value } : r)))}>
                            {accounts.filter((a) => a.accountType !== "BANK").map((a) => <option key={a.id} value={a.id}>{a.code} - {a.name}</option>)}
                          </select>
                        </td>
                        <td>
                          <select className="x-select" value={ln.taxRateId} disabled={locked || taxMode === "NO_TAX"} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, taxRateId: e.target.value } : r)))}>
                            {taxRates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                          </select>
                        </td>
                        {regionOptions.length > 0 && (
                          <td>
                            <select className="x-select" value={ln.tracking1OptionId || ""} disabled={locked} onChange={(e) => setLines((p) => p.map((r, j) => (j === i ? { ...r, tracking1OptionId: e.target.value || null } : r)))}>
                              <option value="">—</option>
                              {regionOptions.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                            </select>
                          </td>
                        )}
                        <td className="num"><strong>{fmtAud(taxMode === "INCLUSIVE" ? est.gross : est.net)}</strong></td>
                        <td>
                          {!locked && lines.length > 1 && (
                            <button className="x-btn x-btn-sm" onClick={() => setLines((p) => p.filter((_, j) => j !== i))}><Trash2 size={12} /></button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                {!docLocked ? (
                  <button
                    className="x-btn x-btn-sm"
                    onClick={() => {
                      const isPay = editKind.startsWith("ACCPAY") || editKind === "PO";
                      setLines((p) => [...p, emptyLine(isPay ? defaultPurchAcc : defaultSalesAcc, isPay ? defaultInTax : defaultOutTax)]);
                    }}
                  >
                    + Add a new line
                  </button>
                ) : <div />}
                <div style={{ width: 290, display: "grid", gap: 6, fontSize: 13.5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--xui-ink-muted)" }}>Subtotal</span>
                    <span className="num">${fmtAud(editingDoc && !editUnlocked ? editingDoc.subTotal : estTotals.net)}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ color: "var(--xui-ink-muted)" }}>Total GST</span>
                    <span className="num">${fmtAud(editingDoc && !editUnlocked ? editingDoc.totalTax : estTotals.tax)}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 16, fontWeight: 700, borderTop: "1px solid var(--xui-border)", paddingTop: 6 }}>
                    <span>Total AUD</span>
                    <span className="num">${fmtAud(editingDoc && !editUnlocked ? editingDoc.total : estTotals.gross)}</span>
                  </div>
                  {editingDoc && editingDoc.status === "AUTHORISED" && (
                    <div style={{ display: "flex", justifyContent: "space-between", color: "var(--xui-nav-blue)", fontWeight: 700 }}>
                      <span>Amount Due</span>
                      <span className="num">${fmtAud(editingDoc.amountDue)}</span>
                    </div>
                  )}
                </div>
              </div>
                  </>
                );
              })()}

              {/* Authorised Payments / Cash Refunds & Credit Note Allocation Sections */}
              {!readOnly && editingDoc && editingDoc.status === "AUTHORISED" && Number(editingDoc.amountDue) > 0 && !editUnlocked && (
                <div className="x-card" style={{ marginTop: 18, background: "#f8fafc" }}>
                  <div className="x-card-header">
                    <strong>
                      <CreditCard size={14} style={{ verticalAlign: "middle" }} />{" "}
                      {editingDoc.invoiceType.endsWith("CREDIT") ? "Record Cash Refund" : "Receive / Make Payment"}
                    </strong>
                  </div>
                  <div className="x-card-body" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, alignItems: "end" }}>
                    <div className="x-field"><label>Amount</label><input className="x-input num" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} /></div>
                    <div className="x-field"><label>Date</label><input className="x-input" type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} /></div>
                    <div className="x-field">
                      <label>{editingDoc.invoiceType === "ACCRECCREDIT" ? "Refund From" : editingDoc.invoiceType === "ACCPAYCREDIT" ? "Refund To" : "Paid To / From"}</label>
                      <select className="x-select" value={payBankId} onChange={(e) => setPayBankId(e.target.value)}>
                        {banks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                      </select>
                    </div>
                    <div className="x-field"><label>Reference</label><input className="x-input" value={payRef} onChange={(e) => setPayRef(e.target.value)} /></div>
                    <button className="x-btn x-btn-green" onClick={handleRecordPayment}>
                      {editingDoc.invoiceType.endsWith("CREDIT") ? "Record Refund" : "Add Payment"}
                    </button>
                  </div>
                </div>
              )}

              {editingDoc && editingDoc.payments.length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <strong style={{ fontSize: 13 }}>
                    {editingDoc.invoiceType.endsWith("CREDIT") ? "Recorded Cash Refunds" : "Recorded Payments"}
                  </strong>
                  <table className="x-table" style={{ marginTop: 6 }}>
                    <thead><tr><th>Date</th><th>Account</th><th>Reference</th><th>Reconciled</th><th className="num">Amount</th><th></th></tr></thead>
                    <tbody>
                      {editingDoc.payments.map((p) => (
                        <tr key={p.id}>
                          <td>{p.paymentDate}</td><td>{p.bankAccountName}</td><td>{p.reference || "—"}</td>
                          <td><span className={`x-badge ${p.isReconciled ? "green" : ""}`}>{p.isReconciled ? "Reconciled" : "Unreconciled"}</span></td>
                          <td className="num">${fmtAud(p.amount)}</td>
                          <td>
                            {!readOnly && (
                              <button className="x-btn x-btn-sm x-btn-danger" onClick={() => handleDeletePayment(p.id)}>Remove &amp; Reverse</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {editingDoc && editingDoc.allocations && editingDoc.allocations.length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <strong style={{ fontSize: 13 }}>Credit Note Allocations</strong>
                  <table className="x-table" style={{ marginTop: 6 }}>
                    <thead><tr><th>Date</th><th>Credit Note</th><th>Target Document</th><th className="num">Amount</th><th></th></tr></thead>
                    <tbody>
                      {editingDoc.allocations.map((al) => (
                        <tr key={al.id}>
                          <td>{al.allocationDate}</td>
                          <td><strong>{al.creditNoteNumber}</strong></td>
                          <td><strong>{al.targetInvoiceNumber}</strong></td>
                          <td className="num">${fmtAud(al.amount)}</td>
                          <td>
                            {!readOnly && (
                              <button className="x-btn x-btn-sm x-btn-danger" onClick={() => handleDeallocate(al.id)}>Unallocate</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {allocOpen && editingDoc && (
                <div className="x-card" style={{ marginTop: 16, borderColor: "var(--xui-nav-blue)" }}>
                  <div className="x-card-header"><strong>Allocate {editingDoc.invoiceNumber} (Remaining: ${fmtAud(editingDoc.amountDue)})</strong></div>
                  <div className="x-card-body">
                    {allocTargets.length === 0 ? (
                      <div style={{ color: "var(--xui-ink-muted)" }}>No open invoices/bills for {editingDoc.contactName}.</div>
                    ) : (
                      <table className="x-table">
                        <thead><tr><th>Document</th><th>Date</th><th className="num">Amount Due</th><th style={{ width: 140 }} className="num">Credit to Allocate</th></tr></thead>
                        <tbody>
                          {allocTargets.map((t) => (
                            <tr key={t.id}>
                              <td><strong>{t.invoiceNumber}</strong></td><td>{t.issueDate}</td>
                              <td className="num">${fmtAud(t.amountDue)}</td>
                              <td><input className="x-input num" value={allocMap[t.id] || ""} onChange={(e) => setAllocMap((m) => ({ ...m, [t.id]: e.target.value }))} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end", gap: 8 }}>
                      <button className="x-btn x-btn-sm" onClick={() => setAllocOpen(false)}>Cancel</button>
                      <button className="x-btn x-btn-sm x-btn-green" disabled={allocTargets.length === 0} onClick={handleSubmitAllocation}>Allocate Credit</button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="x-modal-foot">
              <div style={{ display: "flex", gap: 8 }}>
                {!readOnly && editingDoc && (editingDoc.status === "DRAFT" || editingDoc.status === "SUBMITTED") && (
                  <button className="x-btn x-btn-danger" onClick={() => handleDeleteInvoice(editingDoc)}>
                    <Trash2 size={14} /> Delete Draft
                  </button>
                )}
                {!readOnly && editingDoc && editingDoc.status === "AUTHORISED" && Number(editingDoc.amountPaid) === 0 && Number(editingDoc.amountCredited) === 0 && (
                  <button className="x-btn x-btn-danger" onClick={handleVoidExisting}><Ban size={14} /> Void</button>
                )}
                {!readOnly && editingQuoteOrPo && editingQuoteOrPo.status !== "INVOICED" && editingQuoteOrPo.status !== "BILLED" && (
                  <button
                    className="x-btn x-btn-danger"
                    onClick={() =>
                      editingQuoteOrPo.kind === "QUOTE"
                        ? handleDeleteQuote(editingQuoteOrPo.id, editingQuoteOrPo.docNumber)
                        : handleDeletePo(editingQuoteOrPo.id, editingQuoteOrPo.docNumber)
                    }
                  >
                    <Trash2 size={14} /> Delete
                  </button>
                )}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {!readOnly && editingQuoteOrPo && editingQuoteOrPo.status !== "INVOICED" && editingQuoteOrPo.status !== "BILLED" && (
                  <button className="x-btn x-btn-primary" onClick={() => handleSaveDoc(false)}>Save Changes</button>
                )}
                {!readOnly && !editingQuoteOrPo && (!editingDoc || editingDoc.status === "DRAFT" || editingDoc.status === "SUBMITTED") && (
                  <>
                    <button className="x-btn" onClick={() => handleSaveDoc(false)}>Save as Draft</button>
                    <button className="x-btn x-btn-green" onClick={() => (editingDoc ? handleApproveExisting() : handleSaveDoc(true))}>
                      <Check size={14} /> Approve
                    </button>
                  </>
                )}
                {!readOnly && editingDoc && editingDoc.status === "AUTHORISED" && Number(editingDoc.amountPaid) === 0 && Number(editingDoc.amountCredited) === 0 && (
                  editUnlocked ? (
                    <>
                      <button className="x-btn" onClick={() => openExistingDoc(editingDoc)}>Cancel Edit</button>
                      <button className="x-btn x-btn-green" onClick={() => handleSaveDoc(false)}>Save Changes</button>
                    </>
                  ) : (
                    <button className="x-btn" onClick={() => setEditUnlocked(true)}>Edit Document</button>
                  )
                )}
                {!readOnly && !editUnlocked && editingDoc && editingDoc.status === "AUTHORISED" && editingDoc.invoiceType.endsWith("CREDIT") && Number(editingDoc.amountDue) > 0 && (
                  <button className="x-btn x-btn-primary" onClick={openCreditAllocation}>Allocate Credit Balance</button>
                )}
                <button className="x-btn" onClick={() => setEditorOpen(false)}>Close</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
