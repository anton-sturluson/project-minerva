# 19 — Bare Invocation Shows Help Without Error

## Problem

Five Minerva commands show a `What went wrong: ...` error block when invoked with zero arguments:

| Command | Current behavior | Exit code |
|---|---|---|
| `minerva extract` | help + "no extraction prompt was provided" | 1 |
| `minerva extract-files` | help + "no extraction prompt was provided" | 1 |
| `minerva fileinfo` | help + "no path was provided" | 1 |
| `minerva research` | help + "no research query was provided" | 1 |
| `minerva run` | help + "no command chain was provided" | 1 |

The other seven commands (`sec`, `evidence`, `portfolio`, `brief`, `valuation`, `analyze`, `plot`) are Typer subcommand groups and already show clean help with no error.

## Desired behavior

- *Bare invocation* (zero user-provided args/options): show help text, exit 0, no error message.
- *Partial invocation* (some args but missing a required one): keep the existing `What went wrong` error + help, exit 1.

Example:

```
$ minerva extract          # bare → clean help, exit 0
$ minerva extract -f a.md  # partial (missing question) → error + help, exit 1
```

## Design

### Shared helper

Add a `show_help_if_bare` function to `common.py`:

```python
def show_help_if_bare(ctx: typer.Context, **kwargs: Any) -> None:
    """If every kwarg is None or an empty collection, print help and exit 0."""
    if all(_is_bare_default(v) for v in kwargs.values()):
        typer.echo(ctx.get_help())
        raise typer.Exit(0)
```

With a narrow `_is_bare_default`:

```python
def _is_bare_default(v: Any) -> bool:
    """True only for None or empty list/tuple — the values Typer uses for unprovided args."""
    if v is None:
        return True
    if isinstance(v, (list, tuple)) and len(v) == 0:
        return True
    return False
```

**Why narrow, not falsy:** `extract-files` has `force: bool` (default `False`) and `concurrency: int` (default `4`) on the same callback. A broad falsy check would treat `False` and `0` as "not provided," silently misclassifying real user input. Typer passes `None` for unprovided `Optional` args and `None` for unprovided `list` options — never `""`, `False`, or `0`.

### Per-command changes

Each callback calls `show_help_if_bare(ctx, ...)` as its first line, before any validation. Only pass the *user-facing* parameters that indicate intent — not defaults like `model`, `max_tokens`, `concurrency` that always have values.

| Command | Guard kwargs |
|---|---|
| `extract` | `question`, `file_path`, `questions_file` |
| `extract-files` | `question`, `files`, `files_from`, `questions_file`, `out` |
| `fileinfo` | `path` |
| `research` | `query`, `output` |
| `run` | `command` |

### `run` special case

`run` uses `typer.echo()` directly instead of `abort_with_help`. Refactor to use `show_help_if_bare` for bare invocation, then keep the existing error path for partial invocation (which is currently impossible since `run` only has one arg — but the refactor keeps the pattern consistent).

### Exit code choice

Click/Typer uses exit 0 for `--help`. Our bare-invocation guard also uses exit 0. This is consistent — bare invocation is semantically equivalent to asking for help, not an error.

## TDD plan

### Phase 1 — Tests (RED)

Write tests in `tests/test_harness/test_bare_invocation.py`.

**Unit tests for `_is_bare_default`:**

```python
@pytest.mark.parametrize("value,expected", [
    (None, True),
    ([], True),
    ((), True),
    ("hello", False),
    (["a"], False),
    ("", False),       # Typer never sends "" for unprovided args
    (0, False),        # must not treat 0 as bare
    (False, False),    # must not treat False as bare
    (4, False),        # e.g. default concurrency
])
def test_is_bare_default(value, expected):
    assert _is_bare_default(value) is expected
```

**Bare-invocation tests** via `typer.testing.CliRunner`:

```python
# test_bare_extract_shows_help_without_error
# test_bare_extract_files_shows_help_without_error
# test_bare_fileinfo_shows_help_without_error
# test_bare_research_shows_help_without_error
# test_bare_run_shows_help_without_error
```

Each asserts: exit code 0, output contains `Usage:`, output does NOT contain `What went wrong`.

**Partial-invocation regression tests:**

```python
# test_partial_extract_still_errors
#   minerva extract -f foo.md  → exit 1, "What went wrong"

# test_partial_extract_files_still_errors
#   minerva extract-files -f foo.md  → exit 1, "What went wrong"

# test_partial_research_still_errors
#   minerva research --output foo.md  → exit 1, "What went wrong"
```

**Dispatch path regression test:**

```python
# test_run_dispatch_extract_still_errors
#   minerva run "extract"  → exit 1 (dispatch path unaffected)
```

All tests fail initially (RED).

### Phase 2 — Implementation (GREEN)

1. Add `_is_bare_default` and `show_help_if_bare` to `common.py`.
2. Add `show_help_if_bare(ctx, ...)` as the first line of each of the five callbacks.
3. Refactor `run_command` in `cli.py` to use the shared helper.

Run tests — all pass (GREEN).

### Phase 3 — Verify + install

1. Run full test suite: `uv run pytest tests/test_harness -q`.
2. Compile check: `uv run python -m compileall src/harness`.
3. Global install: `uv tool install --force -e .`.
4. Manual spot-check all 12 commands bare: each shows clean help, exit 0, no error.
5. Manual spot-check partial invocations still error.

## Files touched

| File | Change |
|---|---|
| `src/harness/commands/common.py` | Add `_is_bare_default`, `show_help_if_bare` |
| `src/harness/commands/extract.py` | Add bare-invocation guard to `extract_cli_command` and `extract_files_cli_command` |
| `src/harness/commands/fileinfo.py` | Add bare-invocation guard to `fileinfo_cli_command` |
| `src/harness/commands/research.py` | Add bare-invocation guard to `research_cli_command` |
| `src/harness/cli.py` | Refactor `run_command` to use bare-invocation guard |
| `tests/test_harness/test_bare_invocation.py` | New test file — ~14 tests |
| `docs/INDEX.md` | Add this plan doc |
