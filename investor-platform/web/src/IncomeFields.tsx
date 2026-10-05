import type { Security } from "./records";

export const emptyIncome = {
  income_kind: "",
  income_security_id: "",
  accrual_date: "",
};
export type IncomeDraft = typeof emptyIncome;

export function incomePayload(draft: IncomeDraft) {
  return {
    income_kind: draft.income_kind || null,
    income_security_id: draft.income_kind
      ? draft.income_security_id || null
      : null,
    accrual_date: draft.income_kind === "dividend" ? draft.accrual_date : null,
  };
}

export function IncomeFields({
  value,
  paymentDate,
  securities,
  onChange,
}: {
  value: IncomeDraft;
  paymentDate: string;
  securities: Security[];
  onChange: (field: keyof IncomeDraft, value: string) => void;
}) {
  return (
    <>
      <label>
        Income type
        <select
          aria-label="Income type"
          required
          value={value.income_kind}
          onChange={(e) => {
            if (e.target.value !== value.income_kind) {
              onChange("income_kind", e.target.value);
              onChange("income_security_id", "");
              onChange("accrual_date", "");
            }
          }}
        >
          <option value="">Choose income type</option>
          <option value="dividend">Dividend · gross</option>
          <option value="interest">Interest</option>
          <option value="other">Other investment income</option>
        </select>
      </label>
      {value.income_kind && (
        <label>
          {value.income_kind === "dividend"
            ? "Dividend security"
            : "Income security (optional)"}
          <select
            aria-label={
              value.income_kind === "dividend"
                ? "Dividend security"
                : "Income security"
            }
            required={value.income_kind === "dividend"}
            value={value.income_security_id}
            onChange={(e) => onChange("income_security_id", e.target.value)}
          >
            <option value="">
              {value.income_kind === "dividend"
                ? "Choose security"
                : "Not linked to a security"}
            </option>
            {securities.map((s) => (
              <option key={s.id} value={s.id}>
                {s.ticker} · {s.exchange}
              </option>
            ))}
          </select>
        </label>
      )}
      {value.income_kind === "dividend" && (
        <>
          <label>
            Ex-dividend date
            <input
              aria-label="Ex-dividend date"
              type="date"
              required
              max={paymentDate}
              value={value.accrual_date}
              onChange={(e) => onChange("accrual_date", e.target.value)}
            />
          </label>
          <p className="form-note">
            Effective date is the cash payment date. Enter withholding tax
            separately.
          </p>
        </>
      )}
    </>
  );
}
