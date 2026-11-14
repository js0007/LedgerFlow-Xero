export type UserRole = "ADVISER" | "STANDARD" | "READONLY";

export interface OrgSummary {
  id: string;
  shortCode: string;
  displayName: string;
  countryCode: string;
  baseCurrency: string;
  abn?: string;
  role: UserRole;
}

export interface AuthMeResponse {
  user: { id: string; email: string; displayName: string };
  organisations: OrgSummary[];
}

export interface AccountItem {
  id: string;
  code: string | null;
  name: string;
  accountClass: "ASSET" | "LIABILITY" | "EQUITY" | "REVENUE" | "EXPENSE";
  accountType: string;
  systemAccount: string | null;
  isSystemLocked: boolean;
  manualJournalExcluded: boolean;
  enablePaymentsToAccount: boolean;
  showOnWatchlist: boolean;
  defaultTaxRateId: string | null;
  defaultTaxName: string | null;
  defaultTaxCode: string | null;
  description: string | null;
  bankAccountNumber: string | null;
  status: string;
  ytdBalance: string;
}

export interface TaxRateItem {
  id: string;
  code: string;
  name: string;
  rateDecimal: string;
  ratePercent: string;
  basFields: string[];
  canApplyToAssets: boolean;
  canApplyToEquity: boolean;
  canApplyToExpenses: boolean;
  canApplyToLiabilities: boolean;
  canApplyToRevenue: boolean;
  isSystem: boolean;
  status: string;
}

export interface TrackingCategory {
  id: string;
  name: string;
  status: string;
  options: { id: string; name: string; status: string }[];
}

export interface ProductItem {
  id: string;
  code: string;
  name: string;
  isTracked: boolean;
  costPrice: string | null;
  salePrice: string | null;
  purchaseAccountId: string | null;
  purchaseTaxRateId: string | null;
  salesAccountId: string | null;
  salesTaxRateId: string | null;
  quantityOnHand: string | null;
  avgCost: string | null;
}

export interface ContactItem {
  id: string;
  name: string;
  accountNumber: string | null;
  abn: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  isCustomer: boolean;
  isSupplier: boolean;
  defaultSalesAccountId: string | null;
  defaultPurchaseAccountId: string | null;
  defaultSalesTaxRateId: string | null;
  defaultPurchaseTaxRateId: string | null;
  groups: string[];
  theyOwe: string;
  youOwe: string;
}

export interface BankAccountSummary {
  id: string;
  code: string | null;
  name: string;
  bankAccountNumber: string | null;
  currency: string;
  statementBalance: string;
  bookBalance: string;
  difference: string;
  unreconciledCount: number;
}

export interface DashboardData {
  organisation: { id: string; shortCode: string; displayName: string; abn?: string };
  bankAccounts: BankAccountSummary[];
  receivables: { awaitingCount: number; awaitingAmount: string; overdueCount: number; overdueAmount: string };
  payables: { awaitingCount: number; awaitingAmount: string; overdueCount: number; overdueAmount: string };
  watchlist: { id: string; code: string | null; name: string; ytd: string }[];
  recentInvoicePayments: { invoiceNumber: string; contactName: string; date: string; amount: string }[];
}

export interface CommercialLine {
  id?: string;
  lineNo?: number;
  productId?: string | null;
  description: string;
  quantity: string;
  unitAmount: string;
  discountPct: string;
  accountId: string;
  accountCode?: string | null;
  accountName?: string;
  taxRateId: string;
  taxCode?: string;
  taxName?: string;
  netAmount?: string;
  taxAmount?: string;
  grossAmount?: string;
  tracking1OptionId?: string | null;
  tracking2OptionId?: string | null;
}

export interface InvoiceDocument {
  id: string;
  orgId: string;
  invoiceType: "ACCREC" | "ACCPAY" | "ACCRECCREDIT" | "ACCPAYCREDIT";
  contactId: string;
  contactName: string;
  contactEmail?: string | null;
  invoiceNumber: string;
  reference: string | null;
  issueDate: string;
  dueDate: string;
  taxMode: "INCLUSIVE" | "EXCLUSIVE" | "NO_TAX";
  status: "DRAFT" | "SUBMITTED" | "AUTHORISED" | "PAID" | "VOIDED";
  subTotal: string;
  totalTax: string;
  total: string;
  amountPaid: string;
  amountCredited: string;
  amountDue: string;
  postedJournalNumber: number | null;
  version?: number;
  lines: CommercialLine[];
  payments: { id: string; bankAccountName: string; paymentDate: string; amount: string; reference: string | null; isReconciled: boolean; journalNumber: number }[];
  allocations: { id: string; creditNoteNumber: string; targetInvoiceNumber: string; allocationDate: string; amount: string }[];
}

export interface ManualJournalDoc {
  id: string;
  narration: string;
  journalDate: string;
  autoReversingDate: string | null;
  taxMode: "NO_TAX" | "EXCLUSIVE" | "INCLUSIVE";
  showOnCashBasis: boolean;
  status: "DRAFT" | "POSTED" | "VOIDED" | "ARCHIVED";
  postedJournalNumber: number | null;
  reversalJournalNumber: number | null;
  totalDebit: string;
  totalCredit: string;
  taxTotal: string;
  lines: {
    id?: string;
    description: string;
    accountId: string;
    accountCode?: string;
    accountName?: string;
    taxRateId: string;
    taxName?: string;
    debit: string;
    credit: string;
    netAmount?: string;
    taxAmount?: string;
    grossAmount?: string;
    tracking1OptionId?: string | null;
  }[];
}
