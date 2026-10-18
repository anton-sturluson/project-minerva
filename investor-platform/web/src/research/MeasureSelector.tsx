import { useEffect, useRef, useState } from "react";
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
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  const normalized = query.trim().toLowerCase();
  const matches = series.filter(
    (item) =>
      item.name.toLowerCase().includes(normalized) ||
      item.key.includes(normalized),
  );
  function openAll() {
    setQuery("");
    setActive(
      Math.max(
        0,
        series.findIndex((item) => item.key === selected),
      ),
    );
    setOpen(true);
  }
  function close() {
    setOpen(false);
    setQuery("");
  }
  function choose(item: Series) {
    onSelect(item.key);
    close();
  }
  useEffect(() => {
    if (open)
      list.current?.children.item(active)?.scrollIntoView({ block: "nearest" });
  }, [active, open, query]);
  return (
    <div
      className="economics-selector"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) close();
      }}
    >
      <label className="sr-only" htmlFor="economic-measure">
        Measure
      </label>
      <input
        id="economic-measure"
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls="economic-measures"
        aria-activedescendant={
          open && matches[active]
            ? `economic-measure-${matches[active].key}`
            : undefined
        }
        aria-describedby="economic-measure-help"
        value={open ? query : selectedName}
        placeholder={selectedName || "Search measures…"}
        onFocus={openAll}
        onClick={() => {
          if (!open) openAll();
        }}
        onChange={(event) => {
          setQuery(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            close();
          }
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            if (!open) openAll();
            else
              setActive((current) =>
                Math.max(
                  0,
                  Math.min(
                    matches.length - 1,
                    current + (event.key === "ArrowDown" ? 1 : -1),
                  ),
                ),
              );
          }
          if (event.key === "Enter" && open) {
            event.preventDefault();
            if (matches[active]) choose(matches[active]);
          }
        }}
      />
      <span className="economics-selector-caret" aria-hidden="true">
        ▾
      </span>
      <span className="sr-only" id="economic-measure-help">
        Type to search measures. Use arrow keys and Enter to select.
      </span>
      {open && (
        <ul
          id="economic-measures"
          role="listbox"
          aria-label="Measures"
          ref={list}
        >
          {matches.map((item, index) => (
            <li
              key={item.key}
              id={`economic-measure-${item.key}`}
              role="option"
              aria-selected={item.key === selected}
              data-active={index === active}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(item)}
            >
              {item.name}
            </li>
          ))}
          {matches.length === 0 && (
            <li role="presentation">
              <span role="status">No matching measures.</span>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
