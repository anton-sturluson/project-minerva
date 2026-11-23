import { useEffect, useRef, useState } from "react";
import { api } from "../api";

type SymbolMapping = { symbol: string | null; retryable?: boolean };

export function securityLabel(name: string, symbol: string | null | undefined) {
  return { label: name, suffix: symbol ? `($${symbol})` : undefined };
}

export function useResearchSymbols(cusips: string[]) {
  const key = [...new Set(cusips)]
    .filter((cusip) => /^[A-Z0-9]{9}$/.test(cusip))
    .sort()
    .join(",");
  const cache = useRef<Record<string, SymbolMapping>>({});
  const [symbols, setSymbols] = useState<Record<string, SymbolMapping>>({});
  useEffect(() => {
    const controller = new AbortController();
    const missing = key
      .split(",")
      .filter((cusip) => cusip && !cache.current[cusip]);
    async function loadSymbols() {
      for (let start = 0; start < missing.length; start += 20) {
        if (controller.signal.aborted) return;
        const batch = missing.slice(start, start + 20);
        try {
          const response = await api<{
            symbols: Record<string, SymbolMapping>;
          }>(
            `/research/activity/symbols?cusips=${batch.join(",")}`,
            { signal: controller.signal },
            20000,
          );
          if (controller.signal.aborted) return;
          const received = Object.fromEntries(
            batch.map((cusip) => [
              cusip,
              response.symbols[cusip] ?? { symbol: null, retryable: true },
            ]),
          );
          const resolved = Object.fromEntries(
            Object.entries(received).filter(
              ([, mapping]) => !mapping.retryable,
            ),
          );
          cache.current = { ...cache.current, ...resolved };
          setSymbols((previous) => ({ ...previous, ...received }));
          if (Object.values(received).some((mapping) => mapping.retryable))
            return;
        } catch {
          if (controller.signal.aborted) return;
          const unavailable = Object.fromEntries(
            batch.map((cusip) => [cusip, { symbol: null }]),
          );
          setSymbols((previous) => ({ ...previous, ...unavailable }));
          return;
        }
      }
    }
    void loadSymbols();
    return () => controller.abort();
  }, [key]);
  return symbols;
}
