# packages/tools — AgentForge tool layer

Import package `agentforge_tools` (pip name `agentforge-tools`). Pinned contracts
(`Tool`, `ToolResult`, `ChartSpec` shapes) live per `docs/INTERFACES.md`; nothing in
this package deviates from them structurally (see DEVIATIONS for conventions).

## File map

| File | Purpose |
|---|---|
| `pyproject.toml` | Packaging: src-layout package, deps pandas/matplotlib/pydantic/httpx. |
| `agentforge_tools/base.py` | Pinned `Tool` ABC, `ToolResult`, `ToolRegistry`, JSON-Schema→pydantic compiler. |
| `agentforge_tools/web_search.py` | `WebSearchTool` + `WebSearchProvider`, DuckDuckGo (keyless) and Brave (`BRAVE_API_KEY`) providers. |
| `agentforge_tools/sandbox.py` | `CodeSandboxTool`: restricted `python -I -c` subprocess execution. |
| `agentforge_tools/files.py` | `FileTools` (read/write/list) workspace-scoped with traversal protection. |
| `agentforge_tools/csv_analyzer.py` | `CSVAnalyzerTool`: describe/correlations/groupbys/trends/segmentation + ChartSpecs. |
| `agentforge_tools/charts.py` | `ChartTool` + `render_chart_spec(spec, out_dir)` helper: ChartSpec → PNG (matplotlib Agg). |
| `agentforge_tools/registry.py` | `build_default_registry(workspace_dir)` wiring all tools to one shared workspace. |
| `tests/` | pytest suite (offline; HTTP mocked with `httpx.MockTransport`). Fixtures in `tests/fixtures/`. |

Run tests from the repo root: `python -m pytest packages/tools/tests -q`
(shared venv at `<repo>/.venv`).

## Design decisions

- **run() never raises.** `ToolRegistry.run` captures every failure mode (unknown
  tool, non-dict inputs, schema violation, exceptions inside tools) as
  `ToolResult(ok=False, error=...)`. Agents branch on `ok`; no try/except needed.
- **Validation = the same JSON Schema the LLM sees.** `parameters_json_schema` is
  compiled once at registration into a pydantic model (`create_model`), supporting
  type/enum/anyOf/array/nested-object/`additionalProperties:false`/defaults.
  Uncompilable schemas degrade to dict-ness checks (warn in logs) rather than
  breaking registration. Validation is a gate for LLM-generated arguments, NOT a
  security boundary (pydantic lax mode coerces, e.g. bool→int).
- **ok semantics for the sandbox** (documented in its docstring): `ok=True` means
  the sandbox *completed a run* — user code exiting non-zero is a *code* failure
  reported via `exit_code`/`stderr`/`data["error"]`. `ok=False` means the tool
  could not complete (timeout, spawn failure, bad inputs).
- **Sandbox artifacts:** any `*.png` the child writes to its cwd is collected and
  copied to `<workspace>/artifacts/sandbox-<id>/` so it outlives the temp dir.
  Non-PNG files stay ephemeral in the temp dir.
- **CSVAnalyzer charts:** builds candidate charts (trend, group means, churn-flag
  pie/rate-by-category, top-correlation scatter, missing-values bar) then orders
  them by keywords in the optional `question` (churn/trend/correlation/quality)
  and returns the top 3–6 as pinned ChartSpecs (ids are positional `chart_1..N`).
- **CSVAnalyzer honesty:** empty files → `ok=False`; header-only files →
  `ok=True` with an explicit note; oversized files are truncated to `CSV_ROW_CAP`
  rows with a note in `summary.notes`; date-like string columns are coerced
  (≥80% parseable on a sample) with a note. Nothing is invented.
- **Web search honesty:** providers raise on failure; the tool converts to
  `ok=False`. DuckDuckGo markup changes parse to *zero* results, never fabricated
  ones. Each DDG result carries a `note` advising verification against sources.

## Sandbox security model (honest version)

What the sandbox IS:

- A fresh `python -I -c` subprocess (isolated mode: ignores `PYTHON*` env vars,
  no user site-packages, cwd not on `sys.path`) with `cwd` set to a fresh temp
  dir and a wall-clock timeout (default 20 s, clamp [1, 120]).
- stdout/stderr captured with char caps (default 100k, env-tunable) and decoded
  with `errors="replace"`.
- Guarded *prelude* injected before user code: patches `socket.socket`,
  `create_connection`, `getaddrinfo`, `gethostbyname*` to raise; patches
  `os.system/popen/exec*/spawn*/fork*` and `subprocess.Popen/run/call/check_*`
  to raise. On POSIX, applies `resource.setrlimit(RLIMIT_AS)` from
  `SANDBOX_MEMORY_MB`. All guards are try/except-wrapped so they can never
  prevent user code from running.

What the sandbox is NOT (no false claims):

- **Not a security boundary against a motivated adversary.** Determined code can
  escape via ctypes/C extensions; the socket/subprocess patches are guardrails
  against *accidental* network/process use by LLM-generated code.
- **Windows has NO hard memory cap.** `resource` is POSIX-only; the prelude
  swallows the ImportError. On Windows the memory env var is accepted and
  documented but unenforced — only timeout + process isolation apply. (Tested:
  the rlimit test is `skipif sys.platform == "win32"`.)
- Temp-dir isolation means the child CAN read most of the filesystem (Python
  needs it to import site-packages); it is prevented from *calling out* to new
  processes, not from reading.

## Env vars

Canonical (also in `.env.example`):

- `BRAVE_API_KEY` — when set, `WebSearchTool` uses Brave automatically; DuckDuckGo (keyless) otherwise.
- `SANDBOX_TIMEOUT_SECONDS` — default wall-clock timeout (20).
- `SANDBOX_MEMORY_MB` — RLIMIT_AS on POSIX; **accepted but unenforced on Windows** (documented limitation).

Extra (tool-local, all optional, defaulted):

- `SANDBOX_MAX_OUTPUT_CHARS` — stdout/stderr cap (100000).
- `FILE_MAX_READ_BYTES` / `FILE_MAX_WRITE_BYTES` — FileTools caps (1 MB / 2 MB).
- `CSV_MAX_FILE_MB` / `CSV_ROW_CAP` — CSV size cap (50 MB) and row cap (100000).

`MPLBACKEND=Agg` is forced in-process (`charts.py`) and in sandbox children —
never a display backend.

## DEVIATIONS

1. `ToolResult.artifacts` convention: chart-shaped artifacts are pinned ChartSpec
   dicts (`csv_analyzer`, and that is what INTERFACES.md's "e.g." anticipates);
   file-shaped artifacts (sandbox PNGs, rendered charts) are
   `{"name", "path", "kind"}` dicts. Both are plain JSON dicts, so the pinned
   `artifacts: list[dict]` contract holds.
2. `CodeSandboxTool` returns `ok=True` with `exit_code != 0` for failing *user
   code* (syntax/runtime errors) — see ok-semantics above. Callers must check
   `exit_code`, not just `ok`, to judge code correctness.
3. `ToolResult.data` for successful web searches includes `count` and a `note`
   field beyond the pinned `{query, results, provider}` (additive only).
4. ChartSpec `id`s produced by `csv_analyzer` are positional (`chart_1..N`),
   matching INTERFACES.md examples; semantic ids from the internal candidates are
   overwritten. `ChartTool` preserves whatever id the caller supplies.
5. Extra optional env vars (SANDBOX_MAX_OUTPUT_CHARS, FILE_MAX_*, CSV_*) beyond
   the canonical list — additive, all defaulted, listed above for .env.example.
6. CPython 3.13 compatibility fix: `_DDGResultParser` state attributes are
   prefixed `_af_` because 3.13's `HTMLParser` now owns a `_pending` buffer
   attribute (plain `_pending` collided inside `close()`).

## Bugs found & fixed during test authoring

- `_DDGResultParser` attribute collision with CPython 3.13 `HTMLParser._pending`
  (TypeError on every DDG parse under Python 3.13.x) — renamed internals (above).
