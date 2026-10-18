import { useEffect, useState } from "react";
import type { Series } from "./Economics";

export function MeasureSelector({
  series,
  selected,
  onSelect,
}: {
  series: Series[];
  selected: string;
  onSelect: (key: string) => void;
}) {
  const selectedName = series.find((item) => item.key === selected)?.name ?? "";
  const [query, setQuery] = useState(selectedName);
  useEffect(() => setQuery(selectedName), [selectedName]);
  const normalized = query.trim().toLowerCase();
  const matches = series.filter(
    (item) =>
      item.name.toLowerCase().includes(normalized) ||
      item.key.includes(normalized),
  );
  return (
    <div className="economics-selector">
      <label className="sr-only" htmlFor="economic-measure">
        Measure
      </label>
      <input
        id="economic-measure"
        type="text"
        list="economic-measures"
        autoComplete="off"
        aria-describedby="economic-measure-help"
        value={query}
        placeholder="Search measures…"
        onFocus={(event) => event.currentTarget.select()}
        onBlur={() => setQuery(selectedName)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setQuery(selectedName);
          if (event.key === "Enter" && matches.length === 1) {
            event.preventDefault();
            setQuery(matches[0].name);
            onSelect(matches[0].key);
          }
        }}
        onChange={(event) => {
          const value = event.target.value;
          setQuery(value);
          const match = series.find(
            (item) =>
              item.name.toLowerCase() === value.trim().toLowerCase() ||
              item.key === value.trim().toLowerCase(),
          );
          if (match) onSelect(match.key);
        }}
      />
      <datalist id="economic-measures">
        {matches.map((item) => (
          <option key={item.key} value={item.name}>
            {item.category === "valuation"
              ? "Market valuation"
              : item.category === "macro"
                ? "Macro indicators"
                : "Household costs"}
          </option>
        ))}
      </datalist>
      <span className="sr-only" id="economic-measure-help">
        Type to search measures. Choose a matching name to change the chart.
      </span>
      {normalized && matches.length === 0 && (
        <span role="status">No matching measures.</span>
      )}
    </div>
  );
}
