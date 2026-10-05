# components/live — Agent 7 additions to the live run view

Additive only. **Nothing here replaces Agent 1's components** — `Timeline`,
`EventLog`, `ArtifactFeed`, `TokenMeter` and `AgentAvatar` (in
`frontend/components/`) are kept exactly as shipped and remain the renderers.
This directory contains the pieces Agent 1's `/runs/[id]` page was missing,
plus the wiring contract for the backend realtime layer
(`backend/realtime/`, also Agent 7).

## 1. `hooks/useRunStreamV2.ts` — drop-in upgrade for `useRunStream`

Agent 1's `hooks/useRunStream.ts` stays the engine (snapshot seeding, WS +
`{"type":"replay","after_seq":N}`, seq dedup, polling fallback, demo bridge).
V2 wraps it and adds three things it lacked:

1. **Artifact data enrichment.** `artifactsFromEvents` (lib/events.ts) sets
   `data: null` on event-derived artifacts, so the backend's structured
   `artifact_created.payload.data` never reached `ArtifactFeed`'s inline
   chart/table previews. V2 re-attaches it (`ArtifactFeed` already renders
   `a.data` — no component changes needed).
2. `simulated: boolean` — true when any payload is labeled
   `"simulated": true` (the backend demo simulator marks its events).
   Render a small "Simulated demo" badge when true.
3. `dataGrounding: string | null` — the `run_started.payload.data_grounding`
   note (e.g. "bundled sample dataset saas_churn.csv (2,000 rows)").

**Wiring (one line):** in `app/runs/[id]/page.tsx` change

```tsx
import { useRunStream } from "@/hooks/useRunStream";
const stream = useRunStream(runId);
```

to

```tsx
import { useRunStreamV2 } from "@/hooks/useRunStreamV2";
const stream = useRunStreamV2(runId);
```

The result type is a superset of `UseRunStreamResult` — every existing
`stream.*` access keeps compiling (`artifacts` is now enriched; everything
else is identical). Nothing else on the page needs to change.

## 2. `components/live/CostBreakdown.tsx` — post-run cost table

Auditable per-agent breakdown (input/output/tokens/cost/share, totals row),
colored by role. Pure presentational, takes the same `TokenUsage` the page
already has; renders `null` until usage exists.

**Wiring:** under the existing TokenMeter card in `/runs/[id]`:

```tsx
import { CostBreakdown } from "@/components/live/CostBreakdown";
...
<Card>
  <CardHeader title="Token & cost meter" />
  <TokenMeter tokenUsage={stream.tokenUsage} />
  {stream.status === "succeeded" || stream.status === "partial" ? (
    <CostBreakdown tokenUsage={stream.tokenUsage} />
  ) : null}
</Card>
```

Optional honesty disclosure when demo content is detected:

```tsx
{stream.simulated ? (
  <p className="px-4 text-xs text-amber-600 dark:text-amber-400">
    Simulated demo run — {stream.dataGrounding ?? "no live LLM was used"}.
  </p>
) : null}
```

## 3. `artifact_created.payload.data` contract (backend ↔ frontend)

Agent 7's producers (backend demo simulator `realtime.simulate`; orchestrator
engines may too) attach structured bodies beyond the pinned payload fields.
`useRunStreamV2` + `ArtifactFeed` render these with zero extra work:

| artifact `kind`   | `payload.data` shape                                            |
|-------------------|-----------------------------------------------------------------|
| `chart`           | ChartSpec (pinned): `{id, kind: bar\|line\|scatter\|pie, title, x_label, y_label, data: [{label,x,y}], notes}` |
| `table`           | `{columns: string[], rows: (string\|number\|null)[][]}`          |
| `text`            | `{markdown: string}`                                             |
| `prediction`      | `{claim, confidence: 0..1, basis}`                               |
| `recommendation`  | `{recommendations: [{title, action, expected_impact, effort, priority}]}` |
| `report_markdown` | `{markdown: string}` (full report body)                          |

Extra payload keys are additive: `simulated: true` on all demo-simulated
payloads, optional `path` for dataset-grounded artifacts.

## 4. Backend realtime surface (for the coordinator)

* `from realtime.broadcaster import get_broadcaster` — full implementation of
  the pinned contract: `async publish(run_id, event)` (also accepts
  `publish(event)`; preserves caller-provided `seq`), `subscribe(run_id)`
  (bounded per-subscriber queues, drop-oldest + `events_dropped` marker so a
  slow client never blocks a run), `history(run_id)`, `replay_after(run_id, seq)`,
  `clear(run_id)`. Replaces the coordinator stub at the same import path.
* `realtime.events` — pinned envelope/pydantic models, `make_event(...)`,
  `chart_spec(...)` helpers.
* `realtime.token_meter` — `TokenMeter` reading env
  `COST_PER_1M_INPUT_TOKENS` / `COST_PER_1M_OUTPUT_TOKENS` (defaults 0.11/0.11).
* `realtime.simulate` — `SimulatedRunPlayer` / `run_simulation(mission,
  template_id?, on_event?, speed?, run_id?)` (~25–45 s scripted run at 1x,
  deterministic, offline). See `backend/realtime/NOTES.md` for one required
  one-line fix in `app/services/runner.py` before the backend picks the player
  over its fallback emitter.
