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

Effort level is the intelligence/latency/cost dial. Pass it explicitly with
every delegation (`delegate-codex.sh --effort`). Partner default is `high`;
reserve `xhigh` for the hardest, quality-critical jobs (expect long
runtimes); drop to `medium` only for genuinely trivial mechanical work.
On a subscription plan, do not economize on effort at the price of rework.

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
