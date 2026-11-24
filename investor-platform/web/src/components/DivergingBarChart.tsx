import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export type DivergingRow = {
  id: string;
  label: string;
  suffix?: string;
  left: number;
  right: number;
};

type Props = {
  title: string;
  rows: readonly DivergingRow[];
  domainMax: number;
  leftLabel: string;
  rightLabel: string;
  unitLabel: string;
  formatValue: (value: number, side: "left" | "right") => string;
  formatTick: (value: number) => string;
  renderDetails: (row: DivergingRow) => ReactNode;
  children?: ReactNode;
};

export function DivergingBarChart({
  title,
  rows,
  domainMax,
  leftLabel,
  rightLabel,
  unitLabel,
  formatValue,
  formatTick,
  renderDetails,
  children,
}: Props) {
  const id = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = rows.find((row) => row.id === selectedId);
  const heading = useRef<HTMLHeadingElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    if (selectedId && !selected) setSelectedId(null);
  }, [selectedId, selected]);
  useEffect(() => {
    if (selectedId && heading.current) {
      heading.current.focus({ preventScroll: true });
      heading.current.scrollIntoView({ block: "start" });
    }
  }, [selectedId]);
  function close() {
    if (selectedId) buttons.current.get(selectedId)?.focus();
    setSelectedId(null);
  }
  return (
    <section
      className="diverging-chart"
      aria-label={title}
      onKeyDown={(event) => {
        if (event.key === "Escape" && selected) {
          event.stopPropagation();
          close();
        }
      }}
    >
      <h4>{title}</h4>
      {children}
      <div className="diverging-legend" aria-hidden="true">
        <span>
          <i className="diverging-left" />
          {leftLabel}
        </span>
        <span>
          <i className="diverging-right" />
          {rightLabel}
        </span>
      </div>
      {rows.length === 0 ? (
        <p role="status">No securities match.</p>
      ) : (
        <>
          <ul className="diverging-rows">
            {rows.map((row) => (
              <li key={row.id}>
                <button
                  ref={(button) => {
                    if (button) buttons.current.set(row.id, button);
                    else buttons.current.delete(row.id);
                  }}
                  className="diverging-row"
                  aria-expanded={selectedId === row.id}
                  aria-controls={`${id}-details`}
                  aria-label={`${row.label}${row.suffix ? ` ${row.suffix}` : ""}: ${leftLabel} ${formatValue(row.left, "left")}; ${rightLabel} ${formatValue(row.right, "right")}.`}
                  onClick={() =>
                    selectedId === row.id ? close() : setSelectedId(row.id)
                  }
                >
                  <span
                    className="diverging-name"
                    title={`${row.label}${row.suffix ? ` ${row.suffix}` : ""}`}
                  >
                    <span className="diverging-issuer">{row.label}</span>
                    {row.suffix && (
                      <>
                        {" "}
                        <span className="diverging-suffix">{row.suffix}</span>
                      </>
                    )}
                  </span>
                  <span className="diverging-plot" aria-hidden="true">
                    {(["left", "right"] as const).map((side) => {
                      const extent = `${(100 * row[side]) / domainMax}%`;
                      return (
                        <span className="diverging-half" key={side}>
                          <span
                            className={`diverging-bar diverging-${side}`}
                            style={{ width: extent }}
                          />
                          {row[side] > 0 && (
                            <span
                              className={`diverging-value diverging-value-${side}`}
                              style={
                                side === "left"
                                  ? { right: extent }
                                  : { left: extent }
                              }
                            >
                              {formatValue(row[side], side)}
                            </span>
                          )}
                        </span>
                      );
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="diverging-axis" aria-hidden="true">
            <div className="diverging-ticks">
              {[-domainMax, -domainMax / 2, 0, domainMax / 2, domainMax].map(
                (value) => (
                  <span
                    key={value}
                    style={{ left: `${50 + (value / domainMax) * 50}%` }}
                  >
                    {formatTick(value)}
                  </span>
                ),
              )}
            </div>
          </div>
          <p className="diverging-unit">{unitLabel}</p>
        </>
      )}
      {selected && (
        <section
          id={`${id}-details`}
          className="diverging-details"
          aria-labelledby={`${id}-heading`}
        >
          <div className="diverging-detail-heading">
            <h5 id={`${id}-heading`} ref={heading} tabIndex={-1}>
              {selected.label}
              {selected.suffix && ` ${selected.suffix}`}
            </h5>
            <button onClick={close} aria-label="Close security details">
              Close ×
            </button>
          </div>
          {renderDetails(selected)}
        </section>
      )}
    </section>
  );
}
