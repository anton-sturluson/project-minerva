export const number = (n: string | null, digits = 2) =>
  n === null
    ? "—"
    : Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
export const percent = (n: string | null, digits = 2) =>
  n === null ? "—" : `${number(String(Number(n) * 100), digits)}%`;
export function quarterLabel(day: string) {
  return `${day.slice(0, 4)} Q${Math.ceil(Number(day.slice(5, 7)) / 3)}`;
}
