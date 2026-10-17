import { useRef } from "react";

export function useIdempotencyKey() {
  const previous = useRef<{ body: string; key: string } | null>(null);
  function keyFor(body: string): string {
    if (previous.current?.body !== body)
      previous.current = { body, key: crypto.randomUUID() };
    return previous.current.key;
  }
  function reset() {
    previous.current = null;
  }
  return { keyFor, reset };
}
