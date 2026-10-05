/**
 * Builds a realistic scripted event stream for a demo run.
 * Replays the exact pinned event envelope types (see INTERFACES.md) with
 * human-feeling delays so the live view animates like a real run.
 */
import type {
  AgentForgeEvent,
  AgentRole,
  Mission,
  Report,
  Subtask,
  Template,
} from "@/lib/types";
import { DEMO_MISSIONS } from "./data";

export interface ScriptedStep {
  type: AgentForgeEvent["type"];
  agent: AgentRole | null;
  payload: Record<string, unknown>;
  /** Delay in ms to wait AFTER the previous event before emitting this one. */
  delayMs: number;
}

/* ------------------------------------------------------------------ */
/* Deterministic pseudo-random (stable per run id — no Math.random)    */
/* ------------------------------------------------------------------ */

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ------------------------------------------------------------------ */
/* Plans                                                               */
/* ------------------------------------------------------------------ */

const GENERIC_PLAN: Subtask[] = [
  { id: "s1", title: "Break the goal into an analysis plan", agent: "planner", depends_on: [], status: "pending" },
  { id: "s2", title: "Research external context and benchmarks", agent: "researcher", depends_on: ["s1"], status: "pending" },
  { id: "s3", title: "Analyze the data", agent: "analyst", depends_on: ["s1"], status: "pending" },
  { id: "s4", title: "Forecast what happens next", agent: "forecaster", depends_on: ["s2", "s3"], status: "pending" },
  { id: "s5", title: "Review claims and rank findings", agent: "critic", depends_on: ["s3", "s4"], status: "pending" },
];

export function planForMission(mission: Mission, template: Template | null): Subtask[] {
  const dag = template?.expected_dag;
  if (dag && dag.length > 0) {
    return dag.map((n) => ({
      id: n.id,
      title: n.title,
      agent: n.agent,
      depends_on: [...n.depends_on],
      status: "pending",
    }));
  }
  return GENERIC_PLAN.map((s) => ({ ...s, depends_on: [...s.depends_on] }));
}

/* ------------------------------------------------------------------ */
/* Role-specific narration                                             */
/* ------------------------------------------------------------------ */

interface RoleNarration {
  thought: string[];
  tool: { tool: string; args_summary: string }[];
  artifactName: string;
  artifactSummary: string;
}

function shortGoal(goal: string): string {
  return goal.length > 64 ? `${goal.slice(0, 63)}…` : goal;
}

function narrationFor(role: AgentRole, mission: Mission, report: Report | null): RoleNarration {
  const goal = shortGoal(mission.goal);
  switch (role) {
    case "planner":
      return {
        thought: [
          `Framing "${goal}" — deciding which specialists this needs and in what order.`,
          "Plan drafted: context first, data second, forecast third, critic before shipping.",
        ],
        tool: [{ tool: "decompose_goal", args_summary: "goal → subtask DAG" }],
        artifactName: "plan.md",
        artifactSummary: "Execution plan with owners and dependencies.",
      };
    case "researcher":
      return {
        thought: [
          "Looking for external context and benchmarks so the analysis has a comparison point.",
          "Found usable sources; noting publication dates and sampling caveats for the critic.",
        ],
        tool: [
          { tool: "web_search", args_summary: 'queries: ["benchmarks", "industry norms"]' },
          { tool: "summarize_sources", args_summary: "6 sources → brief" },
        ],
        artifactName: "research_brief.md",
        artifactSummary: "Summarized external context with per-claim citations.",
      };
    case "analyst":
      return {
        thought: [
          mission.dataset_id
            ? "Loading the uploaded dataset and checking quality before computing anything."
            : "No dataset attached — structuring the numbers we already have for comparison.",
          "Computing segment stats and trends; charts next.",
        ],
        tool: [
          { tool: mission.dataset_id ? "python_sandbox" : "structured_stats", args_summary: "descriptive stats by segment" },
          { tool: "make_chart", args_summary: "trend + segment charts" },
        ],
        artifactName: "analysis_tables.md",
        artifactSummary: "Segment statistics and trend tables backing the report.",
      };
    case "forecaster":
      return {
        thought: [
          "Building a simple, defensible projection from the analyst's numbers.",
          "Writing down confidence and basis for each claim so the critic can attack them.",
        ],
        tool: [{ tool: "scenario_model", args_summary: "status-quo vs intervention scenarios" }],
        artifactName: "forecast.md",
        artifactSummary: "Scenario projections with confidence and basis.",
      };
    case "critic":
      return {
        thought: [
          "Reviewing every claim: looking for confounders, small samples and overconfidence.",
          "Downgraded one claim to medium strength; ranked the rest for the report.",
        ],
        tool: [{ tool: "review_rubric", args_summary: "evidence strength audit" }],
        artifactName: "review_notes.md",
        artifactSummary: "Critique with per-claim strength ratings.",
      };
    default:
      return { thought: [], tool: [], artifactName: "notes.md", artifactSummary: "Working notes." };
  }
}

/* ------------------------------------------------------------------ */
/* Script builder                                                      */
/* ------------------------------------------------------------------ */

export interface BuildScriptInput {
  runId: string;
  mission: Mission;
  template: Template | null;
  report: Report | null;
}

export function buildRunScript(input: BuildScriptInput): ScriptedStep[] {
  const { runId, mission, report } = input;
  const plan = planForMission(mission, input.template);
  const rand = mulberry32(hashString(runId));
  const steps: ScriptedStep[] = [];

  const jitter = (base: number) => Math.round(base * (0.75 + rand() * 0.6));
  const push = (
    type: AgentForgeEvent["type"],
    agent: AgentRole | null,
    payload: Record<string, unknown>,
    delayMs: number,
  ) => steps.push({ type, agent, payload, delayMs });

  // 1. Run starts; planner announces the plan.
  push("run_started", null, {}, 350);
  push("plan_created", "planner", { subtasks: plan }, jitter(700));

  // 2. Planner does its own subtask.
  const plannerTask = plan.find((s) => s.agent === "planner");
  if (plannerTask) {
    push("agent_started", "planner", { subtask_id: plannerTask.id, title: plannerTask.title }, jitter(450));
    const pn = narrationFor("planner", mission, report);
    push("thought_summary", "planner", { subtask_id: plannerTask.id, summary: pn.thought[0] }, jitter(650));
    push("tool_call", "planner", { subtask_id: plannerTask.id, tool: pn.tool[0].tool, args_summary: pn.tool[0].args_summary, ok: true }, jitter(550));
    push("tool_result", "planner", { subtask_id: plannerTask.id, tool: pn.tool[0].tool, args_summary: "plan drafted", ok: true }, jitter(500));
    push("artifact_created", "planner", { subtask_id: plannerTask.id, artifact_id: `${runId}_a_plan`, kind: "text", name: pn.artifactName, summary: pn.artifactSummary }, jitter(500));
    push("step_completed", "planner", { subtask_id: plannerTask.id }, jitter(250));
    push("agent_finished", "planner", {}, jitter(250));
    push(
      "token_update",
      "planner",
      {
        agent: "planner",
        input_tokens: 1800 + Math.round(rand() * 500),
        output_tokens: 900 + Math.round(rand() * 400),
        cost_usd: 0.009 + rand() * 0.003,
        run_total_usd: 0.012,
      },
      jitter(300),
    );
  }

  // 3. Worker agents in plan order (skipping planner and critic).
  let cumulativeCost = 0.012;
  const workers = plan.filter((s) => s.agent !== "planner" && s.agent !== "critic");
  for (const task of workers) {
    const role = task.agent;
    const n = narrationFor(role, mission, report);
    push("agent_started", role, { subtask_id: task.id, title: task.title }, jitter(550));

    n.thought.forEach((summary, i) => {
      push("thought_summary", role, { subtask_id: task.id, summary }, jitter(700) + i * 100);
    });

    n.tool.forEach((t, i) => {
      push("tool_call", role, { subtask_id: task.id, tool: t.tool, args_summary: t.args_summary, ok: true }, jitter(650));
      push("tool_result", role, { subtask_id: task.id, tool: t.tool, args_summary: `${t.tool} ok`, ok: true }, jitter(600));
      // Analyst also emits its charts as artifacts right after its last tool call.
      if (role === "analyst" && report && i === n.tool.length - 1) {
        report.charts.slice(0, 3).forEach((c, ci) => {
          push(
            "artifact_created",
            role,
            {
              subtask_id: task.id,
              artifact_id: `${runId}_a_chart_${c.id}`,
              kind: "chart",
              name: c.title,
              summary: c.notes ?? c.title,
            },
            jitter(500) + ci * 60,
          );
        });
      }
    });

    push("artifact_created", role, { subtask_id: task.id, artifact_id: `${runId}_a_${role}_doc`, kind: "text", name: n.artifactName, summary: n.artifactSummary }, jitter(450));

    // Report-derived structured artifacts at the right moment.
    if (role === "forecaster" && report) {
      report.predictions.slice(0, 3).forEach((p, i) => {
        push("artifact_created", role, { subtask_id: task.id, artifact_id: `${runId}_a_pred_${i}`, kind: "prediction", name: `Prediction ${i + 1}`, summary: p.claim }, jitter(420) + i * 60);
      });
    }

    push("step_completed", role, { subtask_id: task.id }, jitter(220));
    push("agent_finished", role, {}, jitter(240));

    const inTok = 5000 + Math.round(rand() * 7000);
    const outTok = 1200 + Math.round(rand() * 2200);
    const cost = 0.02 + rand() * 0.03;
    cumulativeCost = Math.round((cumulativeCost + cost) * 10000) / 10000;
    push(
      "token_update",
      role,
      { agent: role, input_tokens: inTok, output_tokens: outTok, cost_usd: cost, run_total_usd: cumulativeCost },
      jitter(280),
    );
  }

  // 4. Critic reviews everything.
  const criticTask = plan.find((s) => s.agent === "critic");
  if (criticTask) {
    const cn = narrationFor("critic", mission, report);
    push("agent_started", "critic", { subtask_id: criticTask.id, title: criticTask.title }, jitter(550));
    push("thought_summary", "critic", { subtask_id: criticTask.id, summary: cn.thought[0] }, jitter(750));
    push("tool_call", "critic", { subtask_id: criticTask.id, tool: cn.tool[0].tool, args_summary: cn.tool[0].args_summary, ok: true }, jitter(600));
    push("tool_result", "critic", { subtask_id: criticTask.id, tool: cn.tool[0].tool, args_summary: "review complete", ok: true }, jitter(550));
    push("thought_summary", "critic", { subtask_id: criticTask.id, summary: cn.thought[1] }, jitter(650));
    push("artifact_created", "critic", { subtask_id: criticTask.id, artifact_id: `${runId}_a_critique`, kind: "text", name: cn.artifactName, summary: cn.artifactSummary }, jitter(450));

    if (report) {
      report.recommendations.slice(0, 5).forEach((r, i) => {
        push("artifact_created", "critic", { subtask_id: criticTask.id, artifact_id: `${runId}_a_rec_${i}`, kind: "recommendation", name: `#${r.priority} ${r.title}`, summary: r.expected_impact }, jitter(380) + i * 60);
      });
    }

    push("step_completed", "critic", { subtask_id: criticTask.id }, jitter(220));
    push("agent_finished", "critic", {}, jitter(240));
    const cost = 0.025 + rand() * 0.015;
    cumulativeCost = Math.round((cumulativeCost + cost) * 10000) / 10000;
    push(
      "token_update",
      "critic",
      { agent: "critic", input_tokens: 7400 + Math.round(rand() * 3000), output_tokens: 1300 + Math.round(rand() * 600), cost_usd: cost, run_total_usd: cumulativeCost },
      jitter(280),
    );
  }

  // 5. Finish (or fail) — failure happens only for a deliberately-failing run id.
  if (runId.includes("fail")) {
    push("run_failed", null, { error: "LLM provider unreachable after 3 retries (demo failure mode)", stage: "forecast" }, jitter(700));
  } else {
    push("run_finished", null, { report_ready: report !== null }, jitter(600));
  }

  return steps;
}

/** Total approximate wall-clock time of a script, in seconds. */
export function scriptDurationSec(steps: ScriptedStep[]): number {
  return steps.reduce((acc, s) => acc + s.delayMs, 0) / 1000;
}

/** Rebuild a full event list (already emitted) from a script, for seeds. */
export function scriptToEvents(runId: string, steps: ScriptedStep[], startedAt: Date): AgentForgeEvent[] {
  let seq = 0;
  let t = startedAt.getTime();
  return steps.map((s) => {
    seq += 1;
    t += s.delayMs;
    return {
      type: s.type,
      run_id: runId,
      seq,
      ts: new Date(t).toISOString(),
      agent: s.agent,
      payload: s.payload,
    } as AgentForgeEvent;
  });
}
