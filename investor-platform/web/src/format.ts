export const number = (n: string | null, digits = 2) =>
  n === null
    ? "—"
    : Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
export const percent = (n: string | null) =>
  n === null ? "—" : `${number(String(Number(n) * 100))}%`;
