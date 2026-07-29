# Frontier-Model Prompting Principles (Fable 5 Masterclass distillation)

Shared rules for every agent-to-agent prompt in Partner, both directions.
Distilled from Anthropic's Fable 5 (Mythos) Prompting Masterclass; the
principles transfer to any frontier agentic model, including the Codex side.

## Why-Forward Context

Frontier models perform on *why*, not just *what*. Open every handoff with:

> I'm working on [the larger task] for [who it's for]. They need
> [what the output enables]. With that in mind: [the actual request].

Never send a bare instruction ("refactor this file") without the purpose.

## Brevity Over Exhaustiveness

Short prompts with a clear goal beat long constraint lists. Over-specifying
degrades output — you are constraining a model that would have found the
right approach itself. Specify only genuine blockers as constraints. Do not
port prompt templates written for older, weaker models.

## Explicit Checkpoints

Autonomous agents define their own checkpoints unless you set them:

> Pause only when the work genuinely requires input: a destructive or
> irreversible action, a real scope change, or something only I can
> provide. Otherwise keep going and report back when done.

Put this rule in the goal file and in every delegation packet.

## Effort as a Handoff Parameter

Effort level is the intelligence/latency/cost dial. Prefer `delegate-codex.sh
--host <driver> --role <identity>` so backend, effort, and model resolve
from `搭子，配置`'s config instead of being picked ad hoc per call; pass an
explicit `--effort` only when a specific task genuinely needs to override
its identity's default. Without a `--role` or explicit `--effort`, the tool
falls back to `high` — reserve `xhigh` for the hardest, quality-critical
jobs (expect long runtimes); `medium` only for genuinely trivial mechanical
work. On a subscription plan, do not economize on effort at the price of
rework.

## Resume Instead of Restart

Frontier models occasionally stop early. Recovery is one line, sent to the
same session:

> Continue end-to-end from [last checkpoint]. Reference: [goal file / job
> log]. Report back when complete.

Use `delegate-codex.sh resume` for this — never restart the task from zero.

## Memory Instruction

When an agent has a place to write lessons (rollout memory, memory dir,
mem0), include:

> Store one lesson per note with a one-line summary. Record corrections and
> confirmed approaches alike, including why they mattered. Don't save what
> the repo or chat history already records. Update an existing note rather
> than duplicating it. Delete notes that turn out to be wrong.

## Output Discipline

Dense output keeps the receiving agent's context clean. Every delegation
packet ends with:

> DO NOT send optional commentary. Answer only what was asked — no
> preamble, no unsolicited suggestions, no closing remarks. End with at
> most 3 lines of lessons learned.

This is measured, not folklore: a terse reviewer contract cut reviewer
output by 41% with no loss in judgment quality (Superpowers 6
autoresearch, 25+ controlled experiments).

## Delegate Execution, Don't Downshift the Planner

Saving planner spend means moving execution onto the subscription meter
(Codex), not making the planner do quality-critical work with a cheaper
model. Right-sizing is the default lean, never a hard rule: architecture,
the split decision itself, cross-module integration, security/correctness
paths, and final acceptance stay with the planner even though it is the
expensive seat.

Three execution channels, in order of preference for delegable work:

| Channel | Billing | Shape | Use when |
|---|---|---|---|
| Partner `delegate-codex.sh` | Codex subscription | out-of-process background job, durable state, loop monitoring, resume rework, receipt | a real unit of delegated work: runs while you continue, gets full-reviewed, may need fix rounds |
| Codex subagent (one-shot, e.g. a rescue/second-opinion agent) | Codex subscription | in-process, blocking, no durable state | stuck and want a second diagnosis, or a throwaway assist |
| Claude subagent (Task tool, cheaper Claude tier) | Claude API metered | in-process, isolated context, returns a summary | the step genuinely needs Claude-grade reasoning at a lower tier and the metered spend is acceptable |

Picking *which* Claude subagent to spawn is a separate, three-level lookup —
see "Sub Agent Routing" in `references/claude-driven.md`: a `partner-*`
namespaced agent configured via `搭子，配置` first, the user's own
similarly-named agent second, the generic `Task` tool last. This is about
which agent definition answers the call, not which channel bills for it.

Only the Codex channels move the whole meter to the subscription; a
cheaper-Claude subagent still bills the API. A subagent is a single-call
primitive; the Partner job is an orchestration layer (submit → monitor →
review → rework → receipt → memory) — pick by whether the work needs that
lifecycle, not by habit.

## Don't Throttle the Planner's Thinking

Restricting the orchestrator's thinking backfires: in controlled runs it
raised turns from 92 to 138 and doubled output — thinking buys turn
efficiency (Superpowers 6 autoresearch). Economize on the execution axis
(delegate downward), never on the planner's reasoning budget.

Do bound the planner's **execution surface**. Reasoning effort and repository
discovery are different dimensions: keep the configured effort, while the
outer host supplies a compact evidence packet and disables tools/subagents for
repository-heavy Claude planning. `references/bounded-planning.md` defines the
packet, timeouts, CLI budget, artifacts, and no-fallback recovery path. This
preserves high-effort judgment without paying the planner to recursively
rediscover the repo.
