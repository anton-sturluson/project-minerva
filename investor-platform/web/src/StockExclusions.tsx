import { useState } from "react";

type Stock = { id: string; ticker: string; exchange: string };

export function StockExclusions({
  stocks,
  selected,
  disabled,
  onChange,
}: {
  stocks: Stock[];
  selected: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const matches = stocks.filter((stock) =>
    `${stock.ticker} ${stock.exchange}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="stock-exclusions">
      <details
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.currentTarget.open = false;
            event.currentTarget.querySelector("summary")?.focus();
          }
        }}
      >
        <summary>
          Excluded stocks{selected.length ? ` (${selected.length})` : ""}
        </summary>
        <div className="stock-options">
          <label>
            Search stocks
            <input
              type="search"
              value={query}
              placeholder="Ticker or exchange"
              disabled={disabled}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <fieldset disabled={disabled}>
            <legend className="sr-only">Stocks to exclude</legend>
            {matches.map((stock) => (
              <label key={stock.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(stock.id)}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...selected, stock.id]
                        : selected.filter((id) => id !== stock.id),
                    )
                  }
                />
                {stock.ticker} · {stock.exchange}
              </label>
            ))}
            {!matches.length && <p role="status">No matching stocks.</p>}
          </fieldset>
        </div>
      </details>
      {selected.length > 0 && (
        <div className="selected-stocks" aria-label="Excluded stocks selection">
          {stocks
            .filter((stock) => selected.includes(stock.id))
            .map((stock) => (
              <button
                key={stock.id}
                type="button"
                disabled={disabled}
                aria-label={`Remove ${stock.ticker} · ${stock.exchange} exclusion`}
                onClick={() =>
                  onChange(selected.filter((id) => id !== stock.id))
                }
              >
                {stock.ticker} · {stock.exchange} ×
              </button>
            ))}
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange([])}
          >
            Clear exclusions
          </button>
        </div>
      )}
    </div>
  );
}
