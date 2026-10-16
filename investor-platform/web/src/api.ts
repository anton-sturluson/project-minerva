export async function api<T>(
  path: string,
  options?: RequestInit,
  timeout = 8000,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
    signal: AbortSignal.timeout(timeout),
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : response.status >= 500
          ? "Could not reach your records. Check the local service and try again."
          : "Check your entries and try again.",
    );
  }
  return response.json() as Promise<T>;
}
export function errorMessage(error: unknown): string {
  return error instanceof Error &&
    error.name !== "TypeError" &&
    error.name !== "TimeoutError"
    ? error.message
    : "Could not reach your records. Check the local service and try again.";
}
export type Account = {
  id: string;
  name: string;
  base_currency: string;
  created_at: string;
  reconstruction?: {
    funding_status?: "recorded" | "inferred" | "reconciled";
    cash_method?: "purchase_shortfall";
    dividend_policy?: "unrecorded_zero" | null;
    warning: string;
    source_sha256: string;
    imported_trades: number;
    skipped: { row: number; reason: string }[];
    opening_cash?: string | null;
    opening_positions: Record<string, string>;
    price_discrepancies: number[];
  } | null;
};
