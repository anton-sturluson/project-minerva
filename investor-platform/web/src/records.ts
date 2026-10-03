export type Security = {
  id: string;
  ticker: string;
  exchange: string;
  currency: string;
};
export type Entry = {
  id: number;
  kind: string;
  effective_date: string;
  amount: string;
  currency: string;
  note: string;
  created_at: string;
  created_by: string;
  security: Security | null;
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
export const today = () => new Date().toISOString().slice(0, 10);
export const labels: Record<string, string> = {
  opening_cash: "Opening cash",
  deposit: "Deposit",
  income: "Investment income",
  withdrawal: "Withdrawal",
  opening_position: "Opening position",
  buy: "Buy",
  sell: "Sell",
};
