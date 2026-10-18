import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { MacroOverview } from "./MacroOverview";
import { dateLabel, valueLabel } from "./economicsFormat";

export type Source = {
  id: string;
  name: string;
  url: string;
  publication_frequency: string;
  publication_schedule: string;
  polling_frequency: string;
  cadence_url: string;
  enabled: boolean;
  disabled_reason: string | null;
  status: string;
  last_attempt: string | null;
  last_success: string | null;
  next_due: string | null;
  error: string | null;
};
type Observation = {
  date: string;
  value: string | null;
  missing: boolean;
  source_url: string;
  footnotes: Record<string, string>[];
  derived_from: Record<string, string | number>[];
  provisional?: boolean;
};
export type Series = {
  category?: "macro" | "household" | "valuation";
  key: string;
  source_id: string;
  name: string;
  unit: string;
  frequency: string;
  description: string;
  methodology_notes: string;
  source_url: string;
  latest: Pick<
    Observation,
    "date" | "value" | "missing" | "provisional"
  > | null;
  observation_count: number;
};
type Catalog = {
  sources: Source[];
  series: Series[];
  automatic_collection_enabled?: boolean;
};
type Detail = Series & { observations: Observation[] };

function checkedLabel(value: string | null): string {
  return value
    ? new Date(value).toLocaleString("en-US", { timeZoneName: "short" })
    : "Never";
}

export function Economics() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let active = true;
    setError("");
    setCatalog(null);
    api<Catalog>("/research/economics").then(
      (data) => {
        if (!active) return;
        setCatalog(data);
        setSelected((current) =>
          data.series.some((item) => item.key === current)
            ? current
            : (data.series.find((item) => item.key === "headline-inflation")
                ?.key ??
              data.series[0]?.key ??
              ""),
        );
      },
      (reason: unknown) => {
        if (active) setError(errorMessage(reason));
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);
  return (
    <section aria-labelledby="economics-heading" className="economics">
      <h3 id="economics-heading" className="sr-only">
        Economics
      </h3>
      {error ? (
        <div role="alert">
          <p>{error}</p>
          <button onClick={() => setAttempt(attempt + 1)}>
            Retry economics
          </button>
        </div>
      ) : !catalog ? (
        <p role="status">Loading economic data…</p>
      ) : (
        <>
          {catalog.series.length === 0 ? (
            <p>No economic series have been added.</p>
          ) : (
            <>
              <label className="economics-selector">
                <span className="sr-only">Measure</span>
                <select
                  aria-label="Measure"
                  value={selected}
                  onChange={(event) => setSelected(event.target.value)}
                >
                  {[
                    ["macro", "Macro indicators"],
                    ["valuation", "Market valuation"],
                    ["household", "Household costs"],
                  ].map(([category, label]) => (
                    <optgroup key={category} label={label}>
                      {catalog.series
                        .filter(
                          (item) => (item.category ?? "household") === category,
                        )
                        .map((item) => (
                          <option key={item.key} value={item.key}>
                            {item.name}
                          </option>
                        ))}
                    </optgroup>
                  ))}
                </select>
              </label>
              {selected && (
                <SeriesDetail
                  key={selected}
                  seriesKey={selected}
                  source={catalog.sources.find(
                    (source) =>
                      source.id ===
                      catalog.series.find((item) => item.key === selected)
                        ?.source_id,
                  )}
                />
              )}
              <details className="economics-overview-details">
                <summary>Latest readings</summary>
                <MacroOverview
                  series={catalog.series}
                  sources={catalog.sources}
                  selected={selected}
                  onSelect={(key) => {
                    setSelected(key);
                    document
                      .getElementById("economic-series-detail")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                />
              </details>
              <details className="economics-household">
                <summary>Household costs</summary>
                <div className="table-scroll" tabIndex={0}>
                  <table className="economics-catalog">
                    <caption>Individual food and household prices</caption>
                    <thead>
                      <tr>
                        <th scope="col">Series</th>
                        <th scope="col">Latest value</th>
                        <th scope="col">Unit</th>
                        <th scope="col">Observation period</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catalog.series
                        .filter(
                          (item) =>
                            !item.category || item.category === "household",
                        )
                        .map((item) => (
                          <tr
                            key={item.key}
                            aria-selected={item.key === selected}
                          >
                            <th scope="row">
                              <button
                                className="economics-series-link"
                                aria-pressed={item.key === selected}
                                onClick={() => setSelected(item.key)}
                              >
                                {item.name}
                              </button>
                            </th>
                            <td className="numeric">
                              {item.latest && !item.latest.missing
                                ? valueLabel(item.latest.value)
                                : "Unavailable"}
                            </td>
                            <td>{item.unit}</td>
                            <td>
                              {item.latest
                                ? dateLabel(item.latest.date, item.frequency)
                                : "Not collected"}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
          <details className="economics-sources">
            <summary>Sources & collection schedule</summary>
            {catalog.automatic_collection_enabled === false && (
              <p>
                Automatic collection is off. Initial data remains available.
              </p>
            )}
            {catalog.automatic_collection_enabled === true && (
              <p>
                Automatic collection is running while the platform is online.
              </p>
            )}
            {catalog.sources.map((source) => (
              <section key={source.id} aria-labelledby={`source-${source.id}`}>
                <h4 id={`source-${source.id}`}>
                  <a href={source.url}>{source.name}</a>
                </h4>
                <dl>
                  <dt>Publication frequency</dt>
                  <dd>{source.publication_frequency}</dd>
                  <dt>Publication schedule</dt>
                  <dd>
                    {source.publication_schedule}{" "}
                    <a href={source.cadence_url}>Publisher schedule</a>
                  </dd>
                  <dt>Collection checks</dt>
                  <dd>
                    {source.enabled ? source.polling_frequency : "Disabled"}
                  </dd>
                  <dt>Last checked</dt>
                  <dd>{checkedLabel(source.last_attempt)}</dd>
                  <dt>Last successful collection</dt>
                  <dd>{checkedLabel(source.last_success)}</dd>
                  {source.enabled &&
                    catalog.automatic_collection_enabled !== false && (
                      <>
                        <dt>Next check due</dt>
                        <dd>
                          {source.next_due
                            ? checkedLabel(source.next_due)
                            : "Not scheduled"}
                        </dd>
                      </>
                    )}
                </dl>
                {!source.enabled && (
                  <p>
                    Unavailable:{" "}
                    {source.disabled_reason ??
                      "Source access has not been configured."}
                  </p>
                )}
                {source.error && (
                  <p role="status">Last collection failed: {source.error}</p>
                )}
              </section>
            ))}
          </details>
        </>
      )}
    </section>
  );
}

function SeriesDetail({
  seriesKey,
  source,
}: {
  seriesKey: string;
  source?: Source;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [bounds, setBounds] = useState({ start: "", end: "" });
  const invalidRange = !!(start && end && start > end);
  useEffect(() => {
    let active = true;
    setDetail(null);
    setError("");
    api<{ series: Series; observations: Observation[] }>(
      `/research/economics/series/${encodeURIComponent(seriesKey)}`,
    ).then(
      (data) => {
        if (!active) return;
        const dates = data.observations
          .filter(
            (point) =>
              !point.missing &&
              point.value !== null &&
              Number.isFinite(Number(point.value)),
          )
          .map((point) => point.date)
          .sort();
        const coverage = { start: dates[0] ?? "", end: dates.at(-1) ?? "" };
        setDetail({ ...data.series, observations: data.observations });
        setBounds(coverage);
        setStart(coverage.start);
        setEnd(coverage.end);
      },
      (reason: unknown) => {
        if (active) setError(errorMessage(reason));
      },
    );
    return () => {
      active = false;
    };
  }, [seriesKey, attempt]);
  const visibleDetail = detail
    ? {
        ...detail,
        observations: detail.observations.filter(
          (point) =>
            (!start || point.date >= start) && (!end || point.date <= end),
        ),
      }
    : null;
  return (
    <section
      id="economic-series-detail"
      className="economics-detail"
      aria-label="Selected economic series"
    >
      <div className="research-controls">
        <label>
          From{" "}
          <input
            type="date"
            value={start}
            disabled={!bounds.start}
            onChange={(event) => setStart(event.target.value)}
          />
        </label>
        <label>
          Through{" "}
          <input
            type="date"
            value={end}
            disabled={!bounds.end}
            onChange={(event) => setEnd(event.target.value)}
          />
        </label>
        {(start || end) && (
          <button
            onClick={() => {
              setStart(bounds.start);
              setEnd(bounds.end);
            }}
          >
            All dates
          </button>
        )}
      </div>
      {invalidRange ? (
        <p role="alert">The end date must be on or after the start date.</p>
      ) : error ? (
        <div role="alert">
          <p>{error}</p>
          <button onClick={() => setAttempt(attempt + 1)}>Retry series</button>
        </div>
      ) : !detail || !visibleDetail ? (
        <p role="status">Loading series…</p>
      ) : (
        <>
          <p className="economics-selected-value">
            <strong>
              {detail.latest && !detail.latest.missing
                ? valueLabel(detail.latest.value)
                : "Unavailable"}
            </strong>{" "}
            {detail.unit}
            {detail.latest && (
              <>
                {" "}
                · {dateLabel(detail.latest.date, detail.frequency)}
                {detail.latest.provisional ? " · Provisional" : ""}
              </>
            )}
          </p>
          <p className="economics-meta">
            {detail.frequency} observations ·{" "}
            <a href={detail.source_url}>Source</a>
          </p>
          {visibleDetail.observations.length === 0 ? (
            <>
              <p>No observations collected for these dates.</p>
              {source?.disabled_reason && (
                <p>
                  {source.disabled_reason} <a href={source.url}>Publisher</a>
                </p>
              )}
            </>
          ) : (
            <>
              <EconomicChart detail={visibleDetail} />
              <details>
                <summary>
                  Data table ({visibleDetail.observations.length} observations)
                </summary>
                <div className="table-scroll" tabIndex={0}>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Observation period</th>
                        <th scope="col">Value ({detail.unit})</th>
                        <th scope="col">Source & notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleDetail.observations.map((point) => (
                        <tr key={point.date}>
                          <th scope="row">
                            {dateLabel(point.date, detail.frequency)}
                          </th>
                          <td className="numeric">
                            {point.missing
                              ? "Unavailable"
                              : valueLabel(point.value)}
                          </td>
                          <td>
                            {point.provisional && (
                              <strong>Provisional · </strong>
                            )}
                            <a href={detail.source_url}>Source</a>
                            {point.footnotes?.length > 0 &&
                              ` · ${point.footnotes.map((note) => note.text ?? Object.values(note).join(": ")).join("; ")}`}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
          {detail.observations.some((point) => point.provisional) && (
            <p className="economics-caution">
              Latest source month is provisional. See data-table notes.
            </p>
          )}
          <details>
            <summary>Methodology</summary>
            <p>{detail.description}</p>
            <p>{detail.methodology_notes}</p>
            <p>
              Observation dates identify the measured period. Collection times
              appear under Sources & collection schedule.
            </p>
          </details>
        </>
      )}
    </section>
  );
}

function EconomicChart({ detail }: { detail: Detail }) {
  const points = [...detail.observations].sort((a, b) =>
    a.date.localeCompare(b.date),
  );
  const valid = points.filter(
    (point) =>
      !point.missing &&
      point.value !== null &&
      Number.isFinite(Number(point.value)),
  );
  if (valid.length === 0)
    return <p>No numeric observations are available to chart.</p>;
  const first = Date.parse(points[0].date);
  const last = Date.parse(points[points.length - 1].date);
  const values = valid.map((point) => Number(point.value));
  const low = Math.min(...values);
  const high = Math.max(...values);
  const padding = (high - low || Math.abs(high) || 1) * 0.08;
  const bottom = low - padding;
  const top = high + padding;
  const x = (date: string) =>
    74 + ((Date.parse(date) - first) / (last - first || 1)) * 656;
  const y = (value: number) => 24 + ((top - value) / (top - bottom)) * 220;
  const stepped =
    detail.key === "fed-target-lower" || detail.key === "fed-target-upper";
  const paths: string[] = [];
  let segment = "";
  let previous = 0;
  const expectedDays = /quarter/i.test(detail.frequency)
    ? 110
    : /month/i.test(detail.frequency)
      ? 45
      : /week/i.test(detail.frequency)
        ? 11
        : Infinity;
  for (const point of points) {
    const time = Date.parse(point.date);
    if (
      point.missing ||
      point.value === null ||
      !Number.isFinite(Number(point.value))
    ) {
      if (segment) paths.push(segment);
      segment = "";
      previous = 0;
      continue;
    }
    if (previous && (time - previous) / 86400000 > expectedDays) {
      if (segment) paths.push(segment);
      segment = "";
    }
    segment += !segment
      ? `M${x(point.date)},${y(Number(point.value))}`
      : stepped
        ? ` H${x(point.date)} V${y(Number(point.value))}`
        : ` L${x(point.date)},${y(Number(point.value))}`;
    previous = time;
  }
  if (segment) paths.push(segment);
  return (
    <figure className="economics-chart" tabIndex={0}>
      <svg
        viewBox="0 0 760 290"
        role="img"
        aria-label={`${detail.name}, ${detail.unit}, ${dateLabel(points[0].date, detail.frequency)} to ${dateLabel(points[points.length - 1].date, detail.frequency)}. Values are in the data table.`}
      >
        {[bottom, (bottom + top) / 2, top].map((tick) => (
          <g key={tick}>
            <line
              x1="74"
              x2="730"
              y1={y(tick)}
              y2={y(tick)}
              className="economics-grid"
            />
            <text x="64" y={y(tick) + 4} textAnchor="end">
              {valueLabel(tick.toFixed(2))}
            </text>
          </g>
        ))}
        {paths.map((path, index) => (
          <path key={index} d={path} className="economics-line" />
        ))}
        {valid.map((point) => (
          <circle
            key={point.date}
            cx={x(point.date)}
            cy={y(Number(point.value))}
            r="2.5"
          >
            <title>
              {dateLabel(point.date, detail.frequency)}:{" "}
              {valueLabel(point.value)} {detail.unit}
            </title>
          </circle>
        ))}
        <text x="74" y="276">
          {dateLabel(points[0].date, detail.frequency)}
        </text>
        <text x="730" y="276" textAnchor="end">
          {last !== first
            ? dateLabel(points[points.length - 1].date, detail.frequency)
            : ""}
        </text>
      </svg>
      <figcaption>
        {stepped
          ? "Policy effective dates; steps preserve each target until the next decision"
          : "Calendar dates"}{" "}
        · {detail.unit}. Missing observations leave gaps.
      </figcaption>
    </figure>
  );
}
