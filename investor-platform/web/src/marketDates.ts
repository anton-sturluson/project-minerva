export const newYorkToday = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });

export function marketDataThroughDate() {
  const hour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "numeric",
      hourCycle: "h23",
    }).format(new Date()),
  );
  const d = new Date(newYorkToday() + "T12:00:00Z");
  if (hour < 17) d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}
