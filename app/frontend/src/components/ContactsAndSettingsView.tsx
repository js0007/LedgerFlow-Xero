import { useEffect, useState } from "react";
import { Building2, Lock, Plus, Search, Store, Tag, Users } from "lucide-react";
import { api, fmtAud } from "../api";
import type {
  AccountItem,
  ContactItem,
  ProductItem,
  TaxRateItem,
  TrackingCategory,
  UserRole,
} from "../types";
import type { RouteKey } from "./TopNav";

interface OrgSettingsData {
  id: string;
  display_name: string;
  legal_name: string | null;
  abn: string | null;
  industry: string | null;
  postal_address: string | null;
  invoice_prefix: string;
}

interface FinSettingsData {
  orgId: string;
  fyEndMonth: number;
  fyEndDay: number;
  gstAccountingMethod: "ACCRUAL" | "CASH";
  basG1Mode: "INCLUSIVE" | "EXCLUSIVE";
  salesTaxDefault: "EXCLUSIVE" | "INCLUSIVE" | "NO_TAX";
  purchasesTaxDefault: "INCLUSIVE" | "EXCLUSIVE" | "NO_TAX";
  softLockDate: string | null;
  hardLockDate: string | null;
}

interface ConnectedAppRow {
  id: string;
  app_slug: string;
  app_name: string;
  category: string;
  status: string;
  scopes: string[];
  connected_at: string;
}

interface Props {
  orgId: string;
  route: RouteKey;
  role: UserRole;
  onNavigate: (r: RouteKey) => void;
  onOrgUpdated?: () => void;
  onToast: (type: "success" | "error" | "info", msg: string) => void;
}

export function ContactsAndSettingsView({ orgId, route, role, onNavigate, onOrgUpdated, onToast }: Props) {
  const canWrite = role !== "READONLY";
  const isAdviser = role === "ADVISER";

  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [taxRates, setTaxRates] = useState<TaxRateItem[]>([]);
  const [tracking, setTracking] = useState<TrackingCategory[]>([]);
  const [connectedApps, setConnectedApps] = useState<ConnectedAppRow[]>([]);

  // Contacts UI
  const [contactTab, setContactTab] = useState<"ALL" | "CUSTOMER" | "SUPPLIER">("ALL");
  const [contactSearch, setContactSearch] = useState("");
  const [contactModal, setContactModal] = useState(false);
  const [editingContact, setEditingContact] = useState<ContactItem | null>(null);
  const [cForm, setCForm] = useState({
    name: "",
    abn: "",
    email: "",
    phone: "",
    address: "",
    isCustomer: true,
    isSupplier: false,
    defaultSalesAccountId: "",
    defaultPurchaseAccountId: "",
    defaultSalesTaxRateId: "",
    defaultPurchaseTaxRateId: "",
  });

  // Products UI
  const [prodModal, setProdModal] = useState(false);
  const [pForm, setPForm] = useState({
    code: "",
    name: "",
    costPrice: "0.00",
    salePrice: "0.00",
    purchaseAccountId: "",
    purchaseTaxRateId: "",
    salesAccountId: "",
    salesTaxRateId: "",
  });

  // Settings UI
  const [settingsTab, setSettingsTab] = useState<"org" | "financial" | "tax" | "tracking">("financial");
  const [orgForm, setOrgForm] = useState({
    displayName: "",
    legalName: "",
    abn: "",
    industry: "",
    postalAddress: "",
    invoicePrefix: "INV-",
  });
  const [finForm, setFinForm] = useState<FinSettingsData>({
    orgId,
    fyEndMonth: 6,
    fyEndDay: 30,
    gstAccountingMethod: "ACCRUAL",
    basG1Mode: "INCLUSIVE",
    salesTaxDefault: "EXCLUSIVE",
    purchasesTaxDefault: "INCLUSIVE",
    softLockDate: "",
    hardLockDate: "",
  });
  const [showArchivedTax, setShowArchivedTax] = useState(false);
  const [newTrackName, setNewTrackName] = useState("");
  const [newTrackOpts, setNewTrackOpts] = useState("");
  const [addOptForCat, setAddOptForCat] = useState<Record<string, string>>({});

  async function loadAll() {
    const [cts, prods, accs, trs, tks] = await Promise.all([
      api.get<ContactItem[]>(`/orgs/${orgId}/contacts`),
      api.get<ProductItem[]>(`/orgs/${orgId}/products`),
      api.get<AccountItem[]>(`/orgs/${orgId}/accounts`),
      api.get<TaxRateItem[]>(`/orgs/${orgId}/tax-rates?includeArchived=true`),
      api.get<TrackingCategory[]>(`/orgs/${orgId}/tracking-categories`),
    ]);
    setContacts(cts);
    setProducts(prods);
    setAccounts(accs);
    setTaxRates(trs);
    setTracking(tks);

    if (route === "settings") {
      const [os, fs] = await Promise.all([
        api.get<OrgSettingsData>(`/orgs/${orgId}/settings/organisation`),
        api.get<FinSettingsData>(`/orgs/${orgId}/settings/financial`),
      ]);
      setOrgForm({
        displayName: os.display_name || "",
        legalName: os.legal_name || "",
        abn: os.abn || "",
        industry: os.industry || "",
        postalAddress: os.postal_address || "",
        invoicePrefix: os.invoice_prefix || "INV-",
      });
      setFinForm({
        ...fs,
        softLockDate: fs.softLockDate || "",
        hardLockDate: fs.hardLockDate || "",
      });
    } else if (route === "app-store") {
      setConnectedApps(await api.get<ConnectedAppRow[]>(`/orgs/${orgId}/connected-apps`));
    }
  }

  useEffect(() => {
    loadAll().catch((e: Error) => onToast("error", e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, route]);

  const activeTaxes = taxRates.filter((t) => showArchivedTax || t.status === "ACTIVE");

  // --- SAVE HANDLERS ---
  async function saveContact() {
    if (!cForm.name.trim()) {
      onToast("error", "Contact name is required.");
      return;
    }
    try {
      if (editingContact) {
        await api.patch(`/orgs/${orgId}/contacts/${editingContact.id}`, {
          name: cForm.name,
          abn: cForm.abn || null,
          email: cForm.email || null,
          phone: cForm.phone || null,
        });
        onToast("success", `Updated contact '${cForm.name}'.`);
      } else {
        await api.post(`/orgs/${orgId}/contacts`, {
          name: cForm.name,
          abn: cForm.abn || null,
          email: cForm.email || null,
          phone: cForm.phone || null,
          address: cForm.address || null,
          isCustomer: cForm.isCustomer,
          isSupplier: cForm.isSupplier,
          defaultSalesAccountId: cForm.defaultSalesAccountId || null,
          defaultPurchaseAccountId: cForm.defaultPurchaseAccountId || null,
          defaultSalesTaxRateId: cForm.defaultSalesTaxRateId || null,
          defaultPurchaseTaxRateId: cForm.defaultPurchaseTaxRateId || null,
        });
        onToast("success", `Created contact '${cForm.name}'.`);
      }
      setContactModal(false);
      await loadAll();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function saveProduct() {
    if (!pForm.code.trim() || !pForm.name.trim()) {
      onToast("error", "Product code and name are required.");
      return;
    }
    try {
      await api.post(`/orgs/${orgId}/products`, {
        code: pForm.code,
        name: pForm.name,
        costPrice: pForm.costPrice,
        salePrice: pForm.salePrice,
        purchaseAccountId: pForm.purchaseAccountId || null,
        purchaseTaxRateId: pForm.purchaseTaxRateId || null,
        salesAccountId: pForm.salesAccountId || null,
        salesTaxRateId: pForm.salesTaxRateId || null,
      });
      onToast("success", `Created item '${pForm.code}'.`);
      setProdModal(false);
      await loadAll();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function saveOrgSettings() {
    try {
      await api.patch(`/orgs/${orgId}/settings/organisation`, orgForm);
      onToast("success", "Organisation details updated.");
      onOrgUpdated?.();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function saveFinSettings() {
    try {
      await api.patch(`/orgs/${orgId}/settings/financial`, {
        fyEndMonth: Number(finForm.fyEndMonth),
        fyEndDay: Number(finForm.fyEndDay),
        gstAccountingMethod: finForm.gstAccountingMethod,
        basG1Mode: finForm.basG1Mode,
        salesTaxDefault: finForm.salesTaxDefault,
        purchasesTaxDefault: finForm.purchasesTaxDefault,
        softLockDate: finForm.softLockDate || null,
        hardLockDate: finForm.hardLockDate || null,
      });
      onToast("success", "Financial settings & lock dates saved.");
      await loadAll();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function createTrackingCategory() {
    if (!newTrackName.trim()) {
      onToast("error", "Category name is required.");
      return;
    }
    try {
      await api.post(`/orgs/${orgId}/tracking-categories`, {
        name: newTrackName.trim(),
        options: newTrackOpts
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
      });
      onToast("success", `Created tracking category '${newTrackName}'.`);
      setNewTrackName("");
      setNewTrackOpts("");
      await loadAll();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  async function addTrackingOption(catId: string) {
    const val = (addOptForCat[catId] || "").trim();
    if (!val) return;
    try {
      await api.post(`/orgs/${orgId}/tracking-categories/${catId}/options`, { name: val });
      onToast("success", `Added tracking option '${val}'.`);
      setAddOptForCat((p) => ({ ...p, [catId]: "" }));
      await loadAll();
    } catch (e) {
      onToast("error", (e as Error).message);
    }
  }

  // === 1. CONTACTS ===
  if (route === "contacts") {
    const filtered = contacts.filter((c) => {
      if (contactTab === "CUSTOMER" && !c.isCustomer) return false;
      if (contactTab === "SUPPLIER" && !c.isSupplier) return false;
      const q = contactSearch.trim().toLowerCase();
      if (q && !`${c.name} ${c.email || ""} ${c.abn || ""}`.toLowerCase().includes(q)) return false;
      return true;
    });
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Contacts &gt; All contacts</div>
            <h1 className="x-page-title">
              <Users size={20} color="var(--xui-nav-blue)" /> Contacts ({filtered.length})
            </h1>
          </div>
          {canWrite && (
            <button
              className="x-btn x-btn-primary"
              onClick={() => {
                setEditingContact(null);
                setCForm({
                  name: "",
                  abn: "",
                  email: "",
                  phone: "",
                  address: "",
                  isCustomer: true,
                  isSupplier: false,
                  defaultSalesAccountId: "",
                  defaultPurchaseAccountId: "",
                  defaultSalesTaxRateId: "",
                  defaultPurchaseTaxRateId: "",
                });
                setContactModal(true);
              }}
            >
              <Plus size={15} /> Add Contact
            </button>
          )}
        </div>
        <main className="x-main">
          <div className="x-card">
            <div className="x-card-header">
              <div className="x-tabs" style={{ marginBottom: 0, borderBottom: "none" }}>
                {(["ALL", "CUSTOMER", "SUPPLIER"] as const).map((t) => (
                  <button key={t} className={`x-tab ${contactTab === t ? "active" : ""}`} onClick={() => setContactTab(t)}>
                    {t === "ALL" ? "All Contacts" : t === "CUSTOMER" ? "Customers" : "Suppliers"}
                  </button>
                ))}
              </div>
              <div style={{ position: "relative", width: 240 }}>
                <Search size={14} style={{ position: "absolute", left: 9, top: 9, color: "var(--xui-ink-muted)" }} />
                <input
                  className="x-input"
                  style={{ paddingLeft: 28 }}
                  placeholder="Search contact or ABN..."
                  value={contactSearch}
                  onChange={(e) => setContactSearch(e.target.value)}
                />
              </div>
            </div>
            <table className="x-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Roles & Groups</th>
                  <th>Email / ABN</th>
                  <th className="num">They owe you</th>
                  <th className="num">You owe them</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.id}>
                    <td style={{ fontWeight: 700 }}>{c.name}</td>
                    <td>
                      {c.isCustomer && <span className="x-badge blue" style={{ marginRight: 4 }}>Customer</span>}
                      {c.isSupplier && <span className="x-badge amber" style={{ marginRight: 4 }}>Supplier</span>}
                      {c.groups.map((g, i) => (
                        <span key={i} className="x-badge" style={{ marginRight: 4 }}>
                          {g}
                        </span>
                      ))}
                    </td>
                    <td>
                      <div>{c.email || "-"}</div>
                      {c.abn && <div style={{ fontSize: 11.5, color: "var(--xui-ink-muted)" }}>ABN {c.abn}</div>}
                    </td>
                    <td className="num" style={{ fontWeight: parseFloat(c.theyOwe) !== 0 ? 700 : 400 }}>
                      {fmtAud(c.theyOwe)}
                    </td>
                    <td className="num" style={{ fontWeight: parseFloat(c.youOwe) !== 0 ? 700 : 400 }}>
                      {fmtAud(c.youOwe)}
                    </td>
                    <td>
                      {canWrite && (
                        <button
                          className="x-btn x-btn-sm"
                          onClick={() => {
                            setEditingContact(c);
                            setCForm({
                              name: c.name,
                              abn: c.abn || "",
                              email: c.email || "",
                              phone: c.phone || "",
                              address: c.address || "",
                              isCustomer: c.isCustomer,
                              isSupplier: c.isSupplier,
                              defaultSalesAccountId: c.defaultSalesAccountId || "",
                              defaultPurchaseAccountId: c.defaultPurchaseAccountId || "",
                              defaultSalesTaxRateId: c.defaultSalesTaxRateId || "",
                              defaultPurchaseTaxRateId: c.defaultPurchaseTaxRateId || "",
                            });
                            setContactModal(true);
                          }}
                        >
                          Edit
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </main>

        {contactModal && (
          <div className="x-modal-backdrop" onClick={() => setContactModal(false)}>
            <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
              <div className="x-modal-head">
                <h3 style={{ margin: 0 }}>{editingContact ? `Edit ${editingContact.name}` : "New Contact"}</h3>
                <button className="x-btn x-btn-sm" onClick={() => setContactModal(false)}>
                  Close
                </button>
              </div>
              <div className="x-modal-body" style={{ display: "grid", gap: 10 }}>
                <div className="x-field">
                  <label>Contact Name</label>
                  <input className="x-input" value={cForm.name} onChange={(e) => setCForm({ ...cForm, name: e.target.value })} />
                </div>
                <div className="x-grid-2">
                  <div className="x-field">
                    <label>ABN</label>
                    <input className="x-input" value={cForm.abn} onChange={(e) => setCForm({ ...cForm, abn: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Email</label>
                    <input className="x-input" value={cForm.email} onChange={(e) => setCForm({ ...cForm, email: e.target.value })} />
                  </div>
                </div>
                {!editingContact && (
                  <div style={{ display: "flex", gap: 18 }}>
                    <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input type="checkbox" checked={cForm.isCustomer} onChange={(e) => setCForm({ ...cForm, isCustomer: e.target.checked })} />
                      Customer
                    </label>
                    <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input type="checkbox" checked={cForm.isSupplier} onChange={(e) => setCForm({ ...cForm, isSupplier: e.target.checked })} />
                      Supplier
                    </label>
                  </div>
                )}
              </div>
              <div className="x-modal-foot">
                <button className="x-btn" onClick={() => setContactModal(false)}>Cancel</button>
                <button className="x-btn x-btn-primary" onClick={saveContact}>Save Contact</button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // === 2. PRODUCTS & SERVICES ===
  if (route === "products") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Business &gt; Products and services</div>
            <h1 className="x-page-title">Products & Services ({products.length})</h1>
          </div>
          {canWrite && (
            <button className="x-btn x-btn-primary" onClick={() => setProdModal(true)}>
              <Plus size={15} /> New Item
            </button>
          )}
        </div>
        <main className="x-main">
          <div className="x-card">
            <table className="x-table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Inventory Type</th>
                  <th className="num">Cost Price</th>
                  <th className="num">Sale Price</th>
                  <th className="num">Qty on Hand</th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => (
                  <tr key={p.id}>
                    <td style={{ fontWeight: 700 }}>{p.code}</td>
                    <td>{p.name}</td>
                    <td>
                      <span className={`x-badge ${p.isTracked ? "blue" : ""}`}>
                        {p.isTracked ? "Tracked Inventory" : "Untracked Service"}
                      </span>
                    </td>
                    <td className="num">{p.costPrice ? fmtAud(p.costPrice) : "-"}</td>
                    <td className="num">{p.salePrice ? fmtAud(p.salePrice) : "-"}</td>
                    <td className="num">{p.isTracked ? p.quantityOnHand : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </main>

        {prodModal && (
          <div className="x-modal-backdrop" onClick={() => setProdModal(false)}>
            <div className="x-modal narrow" onClick={(e) => e.stopPropagation()}>
              <div className="x-modal-head">
                <h3 style={{ margin: 0 }}>New Product / Service Item</h3>
                <button className="x-btn x-btn-sm" onClick={() => setProdModal(false)}>Close</button>
              </div>
              <div className="x-modal-body" style={{ display: "grid", gap: 10 }}>
                <div className="x-grid-2">
                  <div className="x-field">
                    <label>Item Code</label>
                    <input className="x-input" value={pForm.code} onChange={(e) => setPForm({ ...pForm, code: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Item Name</label>
                    <input className="x-input" value={pForm.name} onChange={(e) => setPForm({ ...pForm, name: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Cost Price</label>
                    <input className="x-input" value={pForm.costPrice} onChange={(e) => setPForm({ ...pForm, costPrice: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Sale Price</label>
                    <input className="x-input" value={pForm.salePrice} onChange={(e) => setPForm({ ...pForm, salePrice: e.target.value })} />
                  </div>
                </div>
              </div>
              <div className="x-modal-foot">
                <button className="x-btn" onClick={() => setProdModal(false)}>Cancel</button>
                <button className="x-btn x-btn-primary" onClick={saveProduct}>Save Item</button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  // === 3. SETTINGS HUB (ORG / FINANCIAL LOCKS / AU TAX RATES / TRACKING) ===
  if (route === "settings") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Settings</div>
            <h1 className="x-page-title">Organisation & Accounting Settings</h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-tabs">
            <button className={`x-tab ${settingsTab === "financial" ? "active" : ""}`} onClick={() => setSettingsTab("financial")}>
              Financial Settings & Lock Dates
            </button>
            <button className={`x-tab ${settingsTab === "org" ? "active" : ""}`} onClick={() => setSettingsTab("org")}>
              Organisation Details
            </button>
            <button className={`x-tab ${settingsTab === "tax" ? "active" : ""}`} onClick={() => setSettingsTab("tax")}>
              AU Tax Rates ({taxRates.filter((t) => t.status === "ACTIVE").length}/{taxRates.length})
            </button>
            <button className={`x-tab ${settingsTab === "tracking" ? "active" : ""}`} onClick={() => setSettingsTab("tracking")}>
              Tracking Categories ({tracking.length}/2)
            </button>
          </div>

          {settingsTab === "financial" && (
            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Australian BAS, Tax Defaults & Period Lock Dates</div>
              </div>
              <div className="x-card-body" style={{ display: "grid", gap: 16 }}>
                <div className="x-grid-3">
                  <div className="x-field">
                    <label>Financial Year End Month (AU = 6 / June)</label>
                    <input
                      type="number"
                      className="x-input"
                      value={finForm.fyEndMonth}
                      onChange={(e) => setFinForm({ ...finForm, fyEndMonth: Number(e.target.value) })}
                    />
                  </div>
                  <div className="x-field">
                    <label>GST Accounting Method (BAS)</label>
                    <select
                      className="x-select"
                      value={finForm.gstAccountingMethod}
                      onChange={(e) =>
                        setFinForm({ ...finForm, gstAccountingMethod: e.target.value as "ACCRUAL" | "CASH" })
                      }
                    >
                      <option value="ACCRUAL">Accruals Basis</option>
                      <option value="CASH">Cash Basis</option>
                    </select>
                  </div>
                  <div className="x-field">
                    <label>BAS G1 Total Sales Mode</label>
                    <select
                      className="x-select"
                      value={finForm.basG1Mode}
                      onChange={(e) => setFinForm({ ...finForm, basG1Mode: e.target.value as "INCLUSIVE" | "EXCLUSIVE" })}
                    >
                      <option value="INCLUSIVE">Includes GST (Gross)</option>
                      <option value="EXCLUSIVE">Excludes GST (Net)</option>
                    </select>
                  </div>
                </div>

                <div style={{ borderTop: "1px solid var(--xui-border)", paddingTop: 14 }}>
                  <h4 style={{ margin: "0 0 8px", display: "flex", gap: 6, alignItems: "center" }}>
                    <Lock size={15} /> Two-Tier Period Lock Dates (Adviser Only)
                  </h4>
                  <p style={{ margin: "0 0 12px", fontSize: 12.5, color: "var(--xui-ink-muted)" }}>
                    <strong>Soft Lock:</strong> stops Standard Users posting on or before date (Advisers allowed).{" "}
                    <strong>Hard Lock:</strong> stops ALL users including Advisers (must be on or before Soft Lock Date).
                  </p>
                  <div className="x-grid-2">
                    <div className="x-field">
                      <label>Soft Lock Date (Non-Advisers)</label>
                      <input
                        type="date"
                        className="x-input"
                        disabled={!isAdviser}
                        value={finForm.softLockDate || ""}
                        onChange={(e) => setFinForm({ ...finForm, softLockDate: e.target.value })}
                      />
                    </div>
                    <div className="x-field">
                      <label>Hard Lock Date (All Users incl. Advisers)</label>
                      <input
                        type="date"
                        className="x-input"
                        disabled={!isAdviser}
                        value={finForm.hardLockDate || ""}
                        onChange={(e) => setFinForm({ ...finForm, hardLockDate: e.target.value })}
                      />
                    </div>
                  </div>
                </div>

                {canWrite && (
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button className="x-btn x-btn-primary" onClick={saveFinSettings}>
                      Save Financial Settings
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {settingsTab === "org" && (
            <div className="x-card">
              <div className="x-card-header"><div className="x-card-title">Organisation Profile</div></div>
              <div className="x-card-body" style={{ display: "grid", gap: 12 }}>
                <div className="x-grid-2">
                  <div className="x-field">
                    <label>Display Name</label>
                    <input className="x-input" value={orgForm.displayName} onChange={(e) => setOrgForm({ ...orgForm, displayName: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Legal / Trading Name</label>
                    <input className="x-input" value={orgForm.legalName} onChange={(e) => setOrgForm({ ...orgForm, legalName: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Australian Business Number (ABN)</label>
                    <input className="x-input" value={orgForm.abn} onChange={(e) => setOrgForm({ ...orgForm, abn: e.target.value })} />
                  </div>
                  <div className="x-field">
                    <label>Invoice Prefix</label>
                    <input className="x-input" value={orgForm.invoicePrefix} onChange={(e) => setOrgForm({ ...orgForm, invoicePrefix: e.target.value })} />
                  </div>
                </div>
                <div className="x-field">
                  <label>Postal Address</label>
                  <input className="x-input" value={orgForm.postalAddress} onChange={(e) => setOrgForm({ ...orgForm, postalAddress: e.target.value })} />
                </div>
                {canWrite && (
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button className="x-btn x-btn-primary" onClick={saveOrgSettings}>
                      Save Organisation Details
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {settingsTab === "tax" && (
            <div className="x-card">
              <div className="x-card-header">
                <div className="x-card-title">Australian Tax Rates (6 Active / 11 Total)</div>
                <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5 }}>
                  <input type="checkbox" checked={showArchivedTax} onChange={(e) => setShowArchivedTax(e.target.checked)} />
                  Include Archived Rates (5)
                </label>
              </div>
              <table className="x-table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Tax Rate Name</th>
                    <th className="num">Rate %</th>
                    <th>BAS Boxes</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {activeTaxes.map((t) => (
                    <tr key={t.id}>
                      <td style={{ fontWeight: 700 }}>{t.code}</td>
                      <td>{t.name}</td>
                      <td className="num">{t.ratePercent}%</td>
                      <td>{t.basFields.join(", ") || "-"}</td>
                      <td>
                        <span className={`x-badge ${t.status === "ACTIVE" ? "green" : ""}`}>{t.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {settingsTab === "tracking" && (
            <div className="x-grid-2">
              <div className="x-card">
                <div className="x-card-header"><div className="x-card-title">Active Tracking Categories (Max 2)</div></div>
                <div className="x-card-body" style={{ display: "grid", gap: 14 }}>
                  {tracking.map((tc) => (
                    <div key={tc.id} style={{ border: "1px solid var(--xui-border)", borderRadius: 6, padding: 12 }}>
                      <div style={{ fontWeight: 700, marginBottom: 8 }}>
                        <Tag size={14} style={{ verticalAlign: "middle" }} /> {tc.name}
                      </div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                        {tc.options.map((o) => (
                          <span key={o.id} className="x-badge blue">
                            {o.name}
                          </span>
                        ))}
                      </div>
                      {canWrite && (
                        <div style={{ display: "flex", gap: 6 }}>
                          <input
                            className="x-input"
                            placeholder="New option name..."
                            value={addOptForCat[tc.id] || ""}
                            onChange={(e) => setAddOptForCat((p) => ({ ...p, [tc.id]: e.target.value }))}
                          />
                          <button className="x-btn x-btn-sm" onClick={() => addTrackingOption(tc.id)}>
                            Add Option
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                  {tracking.length === 0 && <div style={{ color: "var(--xui-ink-muted)" }}>No tracking categories configured.</div>}
                </div>
              </div>

              <div className="x-card">
                <div className="x-card-header"><div className="x-card-title">Add Tracking Category</div></div>
                <div className="x-card-body" style={{ display: "grid", gap: 10 }}>
                  <div className="x-field">
                    <label>Category Name</label>
                    <input className="x-input" value={newTrackName} onChange={(e) => setNewTrackName(e.target.value)} placeholder="e.g. Department" />
                  </div>
                  <div className="x-field">
                    <label>Initial Options (comma-separated)</label>
                    <input className="x-input" value={newTrackOpts} onChange={(e) => setNewTrackOpts(e.target.value)} placeholder="Sales, Engineering, Admin" />
                  </div>
                  <button
                    className="x-btn x-btn-primary"
                    disabled={!canWrite || tracking.length >= 2}
                    onClick={createTrackingCategory}
                  >
                    Create Tracking Category ({tracking.length}/2)
                  </button>
                </div>
              </div>
            </div>
          )}
        </main>
      </>
    );
  }

  // === 4. APP STORE / CONNECTED APPS ===
  if (route === "app-store") {
    return (
      <>
        <div className="x-page-header">
          <div>
            <div className="x-breadcrumb">Ecosystem &gt; App Store & Connected Apps</div>
            <h1 className="x-page-title">
              <Store size={20} color="var(--xui-nav-blue)" /> Connected Apps & Marketplace
            </h1>
          </div>
        </div>
        <main className="x-main">
          <div className="x-card" style={{ marginBottom: 16 }}>
            <div className="x-card-header"><div className="x-card-title">Currently Connected Apps ({connectedApps.length})</div></div>
            <div className="x-card-body">
              {connectedApps.length > 0 ? (
                connectedApps.map((app) => (
                  <div key={app.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid #eef1f5" }}>
                    <div>
                      <strong>{app.app_name}</strong> ({app.category}) • Scopes: {app.scopes.join(", ")}
                    </div>
                    <span className="x-badge green">{app.status}</span>
                  </div>
                ))
              ) : (
                <div style={{ color: "var(--xui-ink-muted)" }}>
                  No active third-party OAuth apps connected to this organisation yet.
                </div>
              )}
            </div>
          </div>
          <div className="x-grid-3">
            {[
              { name: "Stripe Payments", cat: "Online Invoice Payments", desc: "Auto-sync invoice payouts and Stripe fees into Business Bank Account." },
              { name: "Dext / Hubdoc", cat: "Bill Capture OCR", desc: "Push supplier PDF receipts directly into Draft Purchases Bills." },
              { name: "Shopify AU", cat: "E-Commerce", desc: "Daily GST-inclusive clearing journal summary synced to 200 Sales." },
            ].map((item) => (
              <div key={item.name} className="x-card">
                <div className="x-card-body">
                  <div className="x-badge blue" style={{ marginBottom: 8 }}>{item.cat}</div>
                  <h4 style={{ margin: "0 0 6px" }}>{item.name}</h4>
                  <p style={{ fontSize: 12.5, color: "var(--xui-ink-muted)", margin: 0 }}>{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </main>
      </>
    );
  }

  // === 5. STAGE-2 OPERATIONAL MODULES (EXPENSES / PAYROLL / FIXED ASSETS / PROJECTS) ===
  const metaMap: Record<string, { title: string; stage: string; desc: string; acctFilter: string[] }> = {
    expenses: {
      title: "Expense Claims & Reimbursements",
      stage: "Stage 2 Planned Module — Mapped to Stage 1 Core GL",
      desc: "Employee out-of-pocket expenses post as Purchases Bills or Spend Money bank lines with GST (INPUT) claimed on BAS 1B.",
      acctFilter: ["420", "429", "493", "835"],
    },
    payroll: {
      title: "Australian Payroll & STP Phase 2",
      stage: "Stage 2 Planned Module — Super & PAYG Withholding Accounts Active in COA",
      desc: "AU Pay Runs debit 477 Wages & Salaries / 478 Superannuation and credit 825 PAYG Withholding Payable & 826 Superannuation Payable.",
      acctFilter: ["477", "478", "804", "825", "826"],
    },
    "fixed-assets": {
      title: "Fixed Assets Register & Depreciation",
      stage: "Stage 2 Planned Module — Asset & Depreciation Accounts Active in COA",
      desc: "Capital purchases (BAS Box G10) are coded using Capital Acquisitions tax codes; monthly depreciation posts via 416 Depreciation -> 711/721 Less Accumulated Depreciation.",
      acctFilter: ["416", "710", "711", "720", "721"],
    },
    projects: {
      title: "Projects & Job Costing",
      stage: "Stage 2 Planned Module — Supported via 2D Tracking Categories in Stage 1",
      desc: "Track project/region profitability today by assigning Tracking Options on Invoices, Bills, and Bank Lines and filtering Profit and Loss.",
      acctFilter: ["200", "300", "310"],
    },
  };
  const info = metaMap[route] || metaMap.expenses;
  const linkedAccounts = accounts.filter((a) => info.acctFilter.includes(a.code || ""));

  return (
    <>
      <div className="x-page-header">
        <div>
          <div className="x-breadcrumb">Xero AU Modules &gt; {info.title}</div>
          <h1 className="x-page-title">
            <Building2 size={20} color="var(--xui-nav-blue)" /> {info.title}
          </h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="x-btn" onClick={() => onNavigate("bills")}>Open Bills</button>
          <button className="x-btn x-btn-primary" onClick={() => onNavigate("manual-journals")}>Post GL Journal</button>
        </div>
      </div>
      <main className="x-main">
        <div className="x-alert info">
          <div>
            <strong>{info.stage}:</strong> {info.desc}
          </div>
        </div>
        <div className="x-card">
          <div className="x-card-header"><div className="x-card-title">Linked Live General Ledger Accounts</div></div>
          <table className="x-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Account Name</th>
                <th>Type</th>
                <th className="num">Live YTD Balance</th>
              </tr>
            </thead>
            <tbody>
              {linkedAccounts.map((a) => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 700 }}>{a.code}</td>
                  <td>{a.name}</td>
                  <td>{a.accountType}</td>
                  <td className="num">{fmtAud(a.ytdBalance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
