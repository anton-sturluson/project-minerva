"""Two-layer output rendering for harness commands."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from harness.context import is_binary, smart_truncate

MAX_OUTPUT_LINES: int = 200
MAX_OUTPUT_BYTES: int = 50 * 1024


@dataclass(slots=True)
class CommandResult:
    """Raw command execution result without presentation metadata in stdout."""

    stdout: bytes = b""
    stderr: bytes = b""
    exit_code: int = 0
    duration_ms: int = 0
    content_type: str = "text"

    @classmethod
    def from_text(
        cls,
        stdout: str = "",
        *,
        stderr: str = "",
        exit_code: int = 0,
        duration_ms: int = 0,
        content_type: str = "text",
    ) -> "CommandResult":
        """Convenience constructor for text-based results."""
        return cls(
            stdout=stdout.encode("utf-8"),
            stderr=stderr.encode("utf-8"),
            exit_code=exit_code,
            duration_ms=duration_ms,
            content_type=content_type,
        )


@dataclass(slots=True)
class OutputEnvelope:
    """Presentation layer for command results."""

    result: CommandResult
    body: str
    full_output_path: Path | None = None

    @property
    def footer(self) -> str:
        """Metadata footer appended to every presented response."""
        return f"[exit:{self.result.exit_code} | {self.result.duration_ms}ms]"

    def render(self) -> str:
        """Render the final display string."""
        if self.body:
            return f"{self.body}\n{self.footer}"
        return self.footer

    @classmethod
    def from_result(
        cls,
        result: CommandResult,
        *,
        workspace_root: Path | None = None,
    ) -> "OutputEnvelope":
        """Build an output envelope from a raw result."""
        parts: list[str] = []
        full_output_path: Path | None = None

        if result.stdout:
            if is_binary(result.stdout):
                parts.append(
                    "Binary output detected. Text preview skipped.\n"
                    "What to do instead: inspect the saved file with `minerva fileinfo <path>` or convert it to text first."
                )
            else:
                stdout_text: str = result.stdout.decode("utf-8", errors="replace")
                if _is_overflow(stdout_text):
                    full_output_path = _write_overflow_artifact(stdout_text, workspace_root)
                    preview: str = smart_truncate(stdout_text, result.content_type)
                    hint_path: str = str(full_output_path) if full_output_path else "(unavailable)"
                    parts.append(
                        f"{preview}\n\n"
                        f"[truncated] Full output saved to {hint_path}\n"
                        "Exploration hints: narrow the command scope, use `--export`, or pipe into `extract` for targeted analysis."
                    )
                else:
                    parts.append(stdout_text)

        stderr_text: str = result.stderr.decode("utf-8", errors="replace").strip()
        if stderr_text and (result.exit_code != 0 or not parts):
            parts.append(stderr_text)

        if not parts:
            parts.append("(no output)")

        return cls(result=result, body="\n\n".join(part.rstrip() for part in parts), full_output_path=full_output_path)


def _is_overflow(text: str) -> bool:
    line_count: int = text.count("\n") + (1 if text else 0)
    size_bytes: int = len(text.encode("utf-8"))
    return line_count > MAX_OUTPUT_LINES or size_bytes > MAX_OUTPUT_BYTES


def _write_overflow_artifact(text: str, workspace_root: Path | None) -> Path | None:
    target_dir: Path = Path(tempfile.gettempdir()) if workspace_root is None else workspace_root / ".minerva-tmp"
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        prefix="overflow-",
        dir=target_dir,
        delete=False,
    ) as handle:
        handle.write(text)
        return Path(handle.name)
