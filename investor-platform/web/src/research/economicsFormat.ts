const dayFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const monthFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  timeZone: "UTC",
});
const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 4,
});

export function dateLabel(value: string, frequency = ""): string {
  if (/quarter/i.test(frequency)) {
    const date = new Date(`${value.slice(0, 10)}T12:00:00Z`);
    return `Q${Math.floor(date.getUTCMonth() / 3) + 1} ${date.getUTCFullYear()}`;
  }
  const formatter = /month/i.test(frequency) ? monthFormatter : dayFormatter;
  return formatter.format(new Date(`${value.slice(0, 10)}T12:00:00Z`));
}

export function valueLabel(value: string | null): string {
  if (value === null || !Number.isFinite(Number(value))) return "Unavailable";
  return numberFormatter.format(Number(value));
}
