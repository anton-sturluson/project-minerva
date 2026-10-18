import type { Series, Source } from "./Economics";
import { dateLabel, valueLabel } from "./economicsFormat";

type Panel = { title: string; keys: string[]; note?: string };
const macroPanels: Panel[] = [
  {
    title: "Inflation",
    keys: ["headline-inflation", "core-pce-inflation"],
    note: "12-month change. Core PCE excludes food and energy.",
  },
  {
    title: "Economic growth",
    keys: ["real-gdp-growth"],
    note: "Real GDP · quarter-on-quarter annualized growth.",
  },
  {
    title: "Jobs",
    keys: ["unemployment", "payroll-growth", "payroll-growth-3m"],
    note: "Payroll changes and their three-month average are in thousands of jobs.",
  },
  {
    title: "Consumer demand",
    keys: ["real-consumption-growth"],
    note: "Real consumer spending · 12-month change.",
  },
  {
    title: "Interest rates",
    keys: ["fed-target-lower", "fed-target-upper", "treasury-10y"],
    note: "Fed target range bounds are separate from the 10-year Treasury yield.",
  },
  {
    title: "Housing finance",
    keys: ["mortgage-30y"],
    note: "Average 30-year fixed mortgage rate, not total housing affordability.",
  },
  {
    title: "Financial stress",
    keys: ["financial-stress"],
    note: "Above zero means above-average historical stress.",
  },
  {
    title: "Fuel",
    keys: ["gasoline"],
    note: "U.S. regular gasoline · EIA weekly benchmark.",
  },
];
const valuationPanels: Panel[] = [
  {
    title: "Shiller CAPE",
    keys: ["cape"],
    note: "Standard CAPE · monthly observations. Latest source estimates may be provisional.",
  },
  {
    title: "Buffett-style equity/GDP proxy",
    keys: ["equity-gdp"],
    note: "Quarterly. Fed publicly traded equity includes closed-end funds and ETFs; divided by nominal annualized GDP for the same quarter.",
  },
];

export function MacroOverview({
  series,
  sources,
  selected,
  onSelect,
}: {
  series: Series[];
  sources: Source[];
  selected: string;
  onSelect: (key: string) => void;
}) {
  const byKey = new Map(series.map((item) => [item.key, item]));
  if (
    !series.some(
      (item) => item.category === "macro" || item.category === "valuation",
    )
  )
    return null;
  function panels(items: Panel[]) {
    return (
      <div className="economics-overview">
        {items.map((panel) => (
          <section
            key={panel.title}
            className="economics-panel"
            aria-label={panel.title}
          >
            <h4>{panel.title}</h4>
            <dl>
              {panel.keys.map((key) => {
                const item = byKey.get(key);
                if (!item)
                  return (
                    <div key={key}>
                      <dt>{key.replaceAll("-", " ")}</dt>
                      <dd>Not collected</dd>
                    </div>
                  );
                return (
                  <div key={key}>
                    <dt>
                      <button
                        className="economics-series-link"
                        aria-pressed={selected === key}
                        aria-controls="economic-series-detail"
                        onClick={() => onSelect(key)}
                      >
                        {item.name}
                      </button>
                    </dt>
                    <dd>
                      <span className="economics-metric">
                        {item.latest && !item.latest.missing
                          ? valueLabel(item.latest.value)
                          : "Unavailable"}
                      </span>{" "}
                      <span className="economics-unit">{item.unit}</span>
                      <small>
                        {item.latest
                          ? dateLabel(item.latest.date, item.frequency)
                          : "Not collected"}
                        {item.latest?.provisional ? " · Provisional" : ""}
                      </small>
                    </dd>
                  </div>
                );
              })}
            </dl>
            {panel.note && <p className="economics-panel-note">{panel.note}</p>}
            {panel.keys.map((key) => {
              const item = byKey.get(key);
              const source = sources.find(
                (source) => source.id === item?.source_id,
              );
              return item &&
                (!item.latest || item.latest.missing) &&
                source?.disabled_reason ? (
                <p key={key} className="economics-panel-note">
                  {source.disabled_reason}{" "}
                  <a href={item.source_url}>Publisher</a>
                </p>
              ) : null;
            })}
          </section>
        ))}
      </div>
    );
  }
  return (
    <>
      <h4 className="economics-section-heading">U.S. macro overview</h4>
      {panels(macroPanels)}
      <h4 className="economics-section-heading">Market valuation</h4>
      {panels(valuationPanels)}
    </>
  );
}
