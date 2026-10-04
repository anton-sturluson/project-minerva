export type Security = {
  id: string;
  ticker: string;
  exchange: string;
  currency: string;
};
export type Entry = {
  id: number;
  kind: EntryKind;
  effective_date: string;
  amount: string;
  currency: string;
  note: string;
  created_at: string;
  created_by: string;
  security: Security | null;
  income_kind?: "dividend" | "interest" | "other" | null;
  income_security?: Security | null;
  accrual_date?: string | null;
  quantity: string | null;
  price: string | null;
  fees: string;
  cost_basis: string | null;
  realized_pnl: string | null;
};
export type Holding = {
  security: Security;
  quantity: string;
  cost_basis: string | null;
};
export type Ledger = {
  balance: string;
  currency: string;
  entries: Entry[];
  holdings: Holding[];
  corrections?: {
    id: number;
    original: Entry;
    replacement: Entry | null;
    reason: string;
    created_at: string;
    created_by: string;
  }[];
};
export function exact(value: string, minimumDecimals = 2) {
  const [whole, fraction = ""] = value.split(".");
  const decimals = fraction.replace(/0+$/, "").padEnd(minimumDecimals, "0");
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") +
    (decimals ? "." + decimals : "")
  );
}
export const today = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
export const labels = {
  opening_cash: "Opening cash",
  deposit: "Deposit",
  income: "Investment income",
  expense: "Fee or tax",
  withdrawal: "Withdrawal",
  opening_position: "Opening position",
  transfer_in: "Receive shares",
  buy: "Buy",
  sell: "Sell",
} as const;
export type EntryKind = keyof typeof labels;
export const cashKinds = [
  "opening_cash",
  "deposit",
  "income",
  "expense",
  "withdrawal",
] as const satisfies readonly EntryKind[];
export const positionKinds = [
  "opening_position",
  "transfer_in",
  "buy",
  "sell",
] as const satisfies readonly EntryKind[];
export type CashKind = (typeof cashKinds)[number];
export type PositionKind = (typeof positionKinds)[number];
export const isPositionKind = (kind: EntryKind): kind is PositionKind =>
  positionKinds.some((value) => value === kind);

export const isInKind = (kind: EntryKind) =>
  kind === "opening_position" || kind === "transfer_in";

export function incomeSecurities(entries: Entry[]) {
  return [
    ...new Map(
      entries
        .flatMap((e) => [e.security, e.income_security])
        .filter((s): s is Security => !!s)
        .map((s) => [s.id, s]),
    ).values(),
  ];
}
