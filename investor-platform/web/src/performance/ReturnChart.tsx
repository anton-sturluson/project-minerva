import type {
  PerformancePoint,
  PerformanceReport,
  BenchmarkMode,
} from "./performanceApi";

export function ReturnChart({
  series: actual,
  scenario,
  benchmarkMode,
  cashMethod,
}: {
  series: PerformancePoint[];
  scenario?: PerformanceReport | null;
  benchmarkMode?: BenchmarkMode;
  cashMethod?: PerformanceReport["cash_method"];
}) {
  const series = actual.map((p, i) => ({
    ...p,
    scenario: scenario?.series[i]?.portfolio ?? null,
  }));
  const keys = ["portfolio", "SPY", "QQQ", "scenario"] as const;
  const values = series.flatMap((p) =>
    keys.flatMap((k) => (p[k] === null ? [] : [Number(p[k]) * 100])),
  );
  const low = Math.min(0, ...values),
    high = Math.max(0.01, ...values),
    span = high - low;
  const elapsed =
    (Date.parse(actual.at(-1)!.date) - Date.parse(actual[0].date)) / 86400000;
  const bucket = (date: string) =>
    elapsed > 730
      ? date.slice(0, 4)
      : elapsed > 180
        ? `${date.slice(0, 4)}-${Math.floor((Number(date.slice(5, 7)) - 1) / 3)}`
        : date.slice(0, 7);
  const ticks = actual.flatMap((point, index) =>
    index > 0 &&
    index < actual.length - 1 &&
    bucket(point.date) !== bucket(actual[index - 1].date)
      ? [
          {
            index,
            date: point.date,
            label:
              elapsed > 730
                ? point.date.slice(0, 4)
                : new Date(point.date + "T12:00:00Z").toLocaleDateString(
                    "en-US",
                    { month: "short", year: "2-digit", timeZone: "UTC" },
                  ),
          },
        ]
      : [],
  );
  if (!ticks.length && actual.length > 3) {
    for (const fraction of [1 / 3, 2 / 3]) {
      const index = Math.floor((actual.length - 1) * fraction);
      if (!ticks.some((tick) => tick.index === index))
        ticks.push({
          index,
          date: actual[index].date,
          label: actual[index].date.slice(5),
        });
    }
  }
  return (
    <figure className="return-chart">
      <figcaption>
        Cumulative return
        {benchmarkMode === "funded_hold"
          ? cashMethod === "recorded"
            ? " · indexes match deposits"
            : " · indexes match purchase funding"
          : benchmarkMode === "matched"
            ? " · matched buys & sales"
            : ""}{" "}
        · <span className="portfolio-key">Portfolio</span> /{" "}
        <span className="spy-key">S&amp;P 500 (SPY)</span> /{" "}
        <span className="qqq-key">Nasdaq-100 (QQQ)</span>
        {scenario && (
          <>
            {" "}
            / <span className="scenario-key">Without excluded stocks</span>
          </>
        )}
      </figcaption>
      <svg
        viewBox="0 0 800 265"
        role="img"
        aria-label={`Cumulative portfolio and benchmark returns from ${actual[0]?.date} to ${actual.at(-1)?.date}`}
      >
        <text x="0" y="16">
          {high.toFixed(1)}%
        </text>
        <text x="0" y="199">
          {low.toFixed(1)}%
        </text>
        <line
          x1="58"
          x2="795"
          y1={195 - ((0 - low) / span) * 175}
          y2={195 - ((0 - low) / span) * 175}
          stroke="currentColor"
          opacity="0.3"
        />
        <g className="chart-dates" aria-label="Chart dates">
          {ticks.map((tick) => {
            const x = 58 + (tick.index / (actual.length - 1)) * 737;
            return (
              <g key={tick.date}>
                <title>{tick.date}</title>
                <line
                  x1={x}
                  x2={x}
                  y1="200"
                  y2="208"
                  stroke="currentColor"
                  opacity="0.4"
                />
                <text
                  x={x}
                  y="226"
                  textAnchor={x < 100 ? "start" : x > 750 ? "end" : "middle"}
                >
                  {tick.label}
                </text>
              </g>
            );
          })}
          <text x="58" y="256">
            {actual[0]?.date}
          </text>
          <text x="795" y="256" textAnchor="end">
            {actual.at(-1)?.date}
          </text>
        </g>
        {keys.map(
          (k, index) =>
            series.every((p) => p[k] !== null) && (
              <polyline
                key={k}
                className={`${k.toLowerCase()}-line`}
                fill="none"
                strokeWidth="2"
                strokeDasharray={
                  index === 1
                    ? "7 4"
                    : index === 2
                      ? "2 4"
                      : index === 3
                        ? "10 3 2 3"
                        : undefined
                }
                points={series
                  .map(
                    (p, i) =>
                      `${58 + (i / (series.length - 1)) * 737},${195 - ((Number(p[k]) * 100 - low) / span) * 175}`,
                  )
                  .join(" ")}
              />
            ),
        )}
      </svg>
    </figure>
  );
}
