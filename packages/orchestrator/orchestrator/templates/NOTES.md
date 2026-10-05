# orchestrator.templates — Agent 8 NOTES

Owner: Agent 8 (marketplace templates). Scope: ONLY
`packages/orchestrator/orchestrator/templates/`.

## What ships

- `market_research.py` — Market Research Team (`market_research_team`):
  researcher x2 + analyst + critic. Outputs: competitor landscape, positioning
  gaps, go-to-market recommendations.
- `sales_insights.py` — Sales Insights Team (`sales_insights_team`): analyst +
  forecaster + critic. Outputs: pipeline/revenue trends, at-risk segments,
  forecast.
- `support_triage.py` — Support Triage Team (`support_triage_team`): researcher
  + analyst + critic. Outputs: complaint themes, resolution-time analysis,
  staffing recommendations.
- `registry.py` — `TEMPLATES` (list, pinned order), `TEMPLATES_BY_ID`,
  `TEMPLATE_IDS`, `get_template` (helpful `KeyError`), `as_api_shape` (deep
  copy with exactly the pinned Template keys), `validate_all` /
  `validate_template`, `is_dag_acyclic` / `dag_problems`.
- `_types.py` — TypedDict views (`TemplateDict`, `TeamMember`, `DagNode`) over
  the pinned shape; runtime values are plain JSON-serializable dicts.
- `tests/` — registry/DAG/prompt tests (`python -m pytest
  packages/orchestrator/orchestrator/templates/tests -q` from repo root).

## Design decisions

1. **Templates are plain dicts, not pydantic models.** The pinned Template
   shape IS a JSON contract (`GET /api/templates` returns it verbatim), and
   the engine's defensive template adapter
   (`orchestrator/planner.py::template_plan`) reads dict fields
   (`node.get("id")`, `node.get("depends_on")`). Plain dicts satisfy the
   engine, the backend, and JSON serialization with zero adaptation. Types are
   documented via TypedDicts in `_types.py`.
2. **`TEMPLATES` is a list** (per brief). The engine's primary path is
   `get_template(id)`, which works with a list registry; the engine's
   secondary fallback (`isinstance(TEMPLATES, dict)` → `.get`) simply never
   triggers. `TEMPLATES_BY_ID` exists for anyone wanting dict access.
3. **No planner member in `team`.** The planner is engine-owned (the engine
   always runs one); templates carry `planner_prompt` instead. `team` lists
   exactly the workers named in the brief. `validate_template` enforces
   exactly one critic per team and that every DAG agent appears in the team.
4. **DAGs are critic-last; the revision step is engine-owned.** The engine's
   `orchestrator.planner.Plan.validate` forbids ANY subtask after the critic
   except the planner's own revision slot (and `Plan.normalize` forces the
   critic to depend on every non-revision subtask). A template DAG with a
   post-critic "finalize" node therefore can NEVER validate — the planner
   logs a cycle warning and silently falls back to heuristic planning, so the
   template would never drive a run. Verified against the engine and locked in
   by `validate_template` (no DAG node may depend on the critic; exactly one
   critic node) and by the integration test
   `test_engine_planner_accepts_every_template_dag`, which runs the engine's
   own `template_plan` on all three templates. Final flows:
   - market_research: t1+t2 researchers (parallel) → t3 analyst gap analysis →
     t4 analyst "Draft go-to-market recommendations" → t5 critic; engine
     appends `t5_rev` (revision pass applying critic fixes).
   - sales_insights: t1 analyst → t2 forecaster → t3 analyst "Draft ranked
     recommendations" → t4 critic; engine appends `t4_rev`.
   - support_triage: t1 analyst + t2 researcher (parallel) → t3 analyst
     "Draft staffing recommendations" → t4 critic; engine appends `t4_rev`.
5. **Prompts mirror the engine's actual worker contracts** (Agent 3,
   `orchestrator/agents/*`) so template prompts and live workers agree:
   researcher → `{thought_summary, findings[], source_urls[], summary}`;
   analyst → `{thought_summary, stats, insights[], charts[ChartSpec],
   summary}`; forecaster → `{predictions[{claim, confidence, basis}],
   summary}`; critic → `{approved, issues[], revision_requests[],
   final_verdict, summary}`. Tool names match Agent 4's registry:
   `web_search`, `csv_analyzer`, `code_sandbox`, `chart`.
6. **Every prompt follows one skeleton**: identity → METHOD (numbered,
   tool-first) → OUTPUT CONTRACT (JSON with field names) → WHAT GOOD LOOKS
   LIKE (concrete pass examples with numbers) → HARD BANS (no invented facts,
   cite sources/numbers, no vague qualifiers) → UNCERTAINTY (how to downgrade
   rather than hide weak evidence). Prompts are team-specific, not generic:
   each analyst defines its thresholds operationally (e.g. "at-risk" = value
   down >20% for 2 consecutive months; theme counts must report volume AND
   percentage; staffing recs must show the volume ÷ tickets-per-agent math).
7. **`report_outline` aligns with Agent 6's style profiles**
   (`orchestrator/report/styles`): market_research requires insights+charts
   (evidence-led), sales_insights leads with recommendations,
   support_triage's exec summary emphasizes predictions. Section names
   reference charts/recommendations so the rendered report matches the
   outline shown in the marketplace.
8. **DAG shape per team.** Market research: two parallel researcher roots →
   analyst synthesis → critic → analyst revision (5 nodes). Sales: analyst →
   forecaster (needs verified stats) → critic over both → analyst revision
   (4 nodes). Support: analyst + researcher in parallel (data vs outside
   view) → critic → analyst revision (4 nodes). All depend_on targets exist;
   all acyclic (Kahn-based `is_dag_acyclic`, tested with hand-built cycles
   and diamonds).
9. **Validation beyond the brief's minimum**: exact key sets (no missing, no
   extra keys, top level + team members + DAG nodes), prompt-length floors
   (200 chars for `system_prompt` and `planner_prompt`), unique DAG node ids,
   DAG agents ⊆ team roles, non-empty tags and report outline.
10. **No import-time side effects; stdlib only.** `validate_all()` is called
    by tests, never at import. The engine can `import orchestrator.templates`
    defensively with zero risk.

## Env vars needed

None. This subpackage is pure static content + stdlib.

## DEVIATIONS

- **No post-critic node in `expected_dag`.** The brief's DAG example shows
  "critic → revision"; implementing that literally breaks the built engine
  (see design decision 4): `template_plan` rejects the plan and the template
  never drives a live run. Instead, recommendation-drafting subtasks run
  before the critic, the critic is the final node, and the revision pass is
  the engine's own auto-appended revision slot — live runs still show
  critic → revision. Recorded here per the INTERFACES.md deviation protocol.
- None from the pinned Template shape or the pinned template ids.
- Two researchers in `market_research_team` share role `"researcher"`
  (distinguished by `title`) — this is per brief ("researcher ×2"), not a
  deviation; the engine maps workers by role, so both run with researcher
  tooling while their prompts target different halves of the research.
- `expected_dag` carries exactly the pinned node keys
  (`id/title/agent/depends_on`); per-node `guidance` was intentionally omitted
  to keep `as_api_shape` output byte-identical to the pinned shape (the
  planner falls back to `planner_prompt` for guidance).
