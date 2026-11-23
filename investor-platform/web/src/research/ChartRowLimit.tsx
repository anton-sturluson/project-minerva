import { useState } from "react";

export function ChartRowLimit({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  return (
    <label>
      Show
      <input
        type="number"
        aria-label="Securities shown"
        min={1}
        step={1}
        max={Number.MAX_SAFE_INTEGER}
        required
        value={draft}
        onChange={(event) => {
          const input = event.currentTarget;
          setDraft(input.value);
          if (
            input.validity.valid &&
            Number.isSafeInteger(input.valueAsNumber)
          ) {
            onChange(input.valueAsNumber);
          }
        }}
        onBlur={() => setDraft(String(value))}
      />
    </label>
  );
}
