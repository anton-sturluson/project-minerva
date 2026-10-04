import type { Report } from "./Tracker";
import { number, percent } from "./format";
import { today } from "./records";

type Point = Report["series"][number];
type Metric = "portfolio" | "SPY" | "QQQ";

function periodReturn(points: Point[], key: Metric): string | null {
  if (points.length < 2 || points.some((point) => point[key] === null))
    return null;
  const start = 1 + Number(points[0][key]);
  return start > 0
    ? String((1 + Number(points.at(-1)![key])) / start - 1)
    : null;
}

export function BenchmarkReturn({
  value,
  portfolio,
  name,
}: {
  value: string | null;
  portfolio: string | null;
  name: string;
}) {
  const difference =
    value === null || portfolio === null
      ? null
      : (Number(portfolio) - Number(value)) * 100;
  // Sign the displayed precision, so tiny rounding noise never appears as -0.00.
  const rounded = difference === null ? null : Number(difference.toFixed(2));
  return (
    <>
      {percent(value)}
      {value !== null && (
        <small
          className={`benchmark-difference ${rounded === null || rounded === 0 ? "" : rounded > 0 ? "gain" : "loss"}`}
          aria-label={`Portfolio minus ${name}`}
          title={`Portfolio minus ${name}, in percentage points`}
        >
          {rounded === null
            ? "—"
            : `${rounded > 0 ? "+" : ""}${number(String(rounded))} pp`}
        </small>
      )}
    </>
  );
}

export function YearlyPerformance({
  report,
  requestedEnd,
}: {
  report: Report;
  requestedEnd: string;
}) {
  const ends = new Map<string, number>();
  report.series.forEach((point, index) =>
    ends.set(point.date.slice(0, 4), index),
  );
  let previous = 0;
  const years = [...ends]
    .flatMap(([year, end]) => {
      const start = previous;
      previous = end;
      if (start === end) return []; // A lone year-end baseline is not a separate year's return.
      const points = report.series.slice(start, end + 1);
      const from = points[0].date;
      const through = points.at(-1)!.date;
      const partialStart = from.slice(0, 4) === year;
      const partialEnd = requestedEnd < `${year}-12-31`;
      const label =
        !partialStart && partialEnd && year === today().slice(0, 4)
          ? "YTD"
          : partialStart || partialEnd
            ? "partial"
            : "";
      const scenarioPoints = report.scenario?.series.filter(
        (point) => from <= point.date && point.date <= through,
      );
      const matchingScenario =
        scenarioPoints?.length === points.length &&
        scenarioPoints[0].date === from &&
        scenarioPoints.at(-1)!.date === through;
      return [
        {
          year,
          from,
          through,
          label,
          portfolio: periodReturn(points, "portfolio"),
          SPY: periodReturn(points, "SPY"),
          QQQ: periodReturn(points, "QQQ"),
          scenario: matchingScenario
            ? periodReturn(scenarioPoints, "portfolio")
            : null,
        },
      ];
    })
    .reverse();
  if (!years.length) return null;
  return (
    <section className="yearly-performance" aria-label="Yearly performance">
      <h3>Yearly performance</h3>
      <div className="table-scroll" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th scope="col">Year</th>
              <th scope="col" className="number">
                Portfolio
              </th>
              {report.scenario && (
                <th scope="col" className="number">
                  Without excluded
                </th>
              )}
              <th scope="col" className="number">
                S&amp;P 500 · SPY <small>Return / Δ</small>
              </th>
              <th scope="col" className="number">
                Nasdaq-100 · QQQ <small>Return / Δ</small>
              </th>
            </tr>
          </thead>
          <tbody>
            {years.map((row) => (
              <tr key={row.year}>
                <th scope="row" title={`${row.from} — ${row.through}`}>
                  {row.year}
                  {row.label && <small> · {row.label}</small>}
                </th>
                <td className="number">{percent(row.portfolio)}</td>
                {report.scenario && (
                  <td className="number">{percent(row.scenario)}</td>
                )}
                <td className="number">
                  <BenchmarkReturn
                    value={row.SPY}
                    portfolio={row.portfolio}
                    name="S&P 500"
                  />
                </td>
                <td className="number">
                  <BenchmarkReturn
                    value={row.QQQ}
                    portfolio={row.portfolio}
                    name="Nasdaq-100"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="form-note">Δ = portfolio − index, in percentage points.</p>
    </section>
  );
}
