export function dateLabel(value: string, frequency = ""): string {
  if (/quarter/i.test(frequency)) {
    const date = new Date(`${value.slice(0, 10)}T12:00:00Z`);
    return `Q${Math.floor(date.getUTCMonth() / 3) + 1} ${date.getUTCFullYear()}`;
  }
  return new Date(`${value.slice(0, 10)}T12:00:00Z`).toLocaleDateString(
    "en-US",
    {
      year: "numeric",
      month: "short",
      day: /month/i.test(frequency) ? undefined : "numeric",
      timeZone: "UTC",
    },
  );
}

export function valueLabel(value: string | null): string {
  if (value === null || !Number.isFinite(Number(value))) return "Unavailable";
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 4 });
}
