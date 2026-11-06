import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { formatMarketTimestamp } from "../format";

type MarketStatus = {
  enabled: boolean;
  worker_alive: boolean;
  last_attempt_at: string | null;
  last_success_at: string | null;
  next_due_at: string | null;
  release: string;
  report: {
    status: string;
    failures: { symbol: string; scope: string; reason: string }[];
  } | null;
};

const timestamp = (value: string | null) =>
  value ? formatMarketTimestamp(value) : "None recorded";

export function MarketDataStatus({ revision }: { revision: number }) {
  const [status, setStatus] = useState<MarketStatus | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void api<MarketStatus>("/market-data/status", { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setStatus(result);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorMessage(failure));
      });
    return () => controller.abort();
  }, [revision, retry]);
  return (
    <section aria-label="Daily price updates" className="form-note">
      {error ? (
        <p role="status">
          Price update status unavailable. {error}{" "}
          <button onClick={() => setRetry((value) => value + 1)}>
            Retry status
          </button>
        </p>
      ) : status ? (
        <>
          <p>
            Daily price updates across all portfolios:{" "}
            {!status.enabled
              ? "disabled"
              : status.worker_alive
                ? "running"
                : "worker stopped"}
            . Last complete update: {timestamp(status.last_success_at)}.
            {status.report && status.report.status !== "complete" && (
              <> Latest attempt: {status.report.status}.</>
            )}
          </p>
          <details>
            <summary>Price update details</summary>
            <p>
              Last attempt: {timestamp(status.last_attempt_at)}. Next due:{" "}
              {timestamp(status.next_due_at)}.
            </p>
            {status.report && status.report.failures.length > 0 && (
              <ul>
                {status.report.failures.map((failure, index) => (
                  <li key={`${failure.symbol}-${failure.scope}-${index}`}>
                    {failure.symbol || "Account"}:{" "}
                    {failure.reason.replaceAll("_", " ")} ({failure.scope})
                  </li>
                ))}
              </ul>
            )}
            <p>Release: {status.release}</p>
          </details>
        </>
      ) : (
        <p>Checking daily price updates…</p>
      )}
    </section>
  );
}
