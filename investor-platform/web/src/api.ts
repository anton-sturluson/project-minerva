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
      typeof detail === "string" ? detail : "Check your entries and try again.",
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
};
