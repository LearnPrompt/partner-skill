# Bounded Claude Planning

Use this path for repository-heavy planning when the configured Partner
identity has `backend=claude`, especially at `xhigh` effort. The outer host
collects facts; Claude only reasons over a compact, explicit packet. This
prevents a Deep Reasoner from turning one planning request into an unbounded
repository scan plus a tree of metered subagents.

The runner is:

```bash
python3 "$PARTNER_DIR/scripts/run-claude-plan.py" \
  --repo "$REPO" \
  --host codex \
  --role deep_reasoner \
  --packet "$REPO/.partner/handoffs/planning-packet.md"
```

It resolves backend, model, and effort only from Partner config. Missing,
unverified, or non-Claude roles fail before the CLI starts. It never chooses a
replacement model. `--allow-unverified` is an explicit diagnostic override,
not a fallback. Changing backend, model, or effort invalidates inherited
verification unless the higher-priority layer explicitly verifies that exact
identity.

## Who Builds The Packet

The outer orchestrator builds it after reading the real repository. Do not ask
the Deep Reasoner to discover its own context. Select only the evidence needed
to decide architecture, scope, risks, and acceptance. If the evidence does not
fit, split the decision or summarize it visibly; never hide truncation.

The packet must be UTF-8, no more than 24,000 characters, and use this exact
contract:

```markdown
# Partner Bounded Planning Packet
## Goal
[One why-forward goal and binary completion condition.]
## Non-goals
[What this change will not do.]
## Current-State Evidence
[Relevant file:line facts, excerpts, commands, and observed failures.]
## Constraints
[Real safety, compatibility, budget, and authorization constraints.]
## Acceptance
[Binary checks that cannot pass by deleting or weakening tests.]
## Open Decisions
[Only decisions the planner must make; write "None." when empty.]
## Truncation
none
```

When evidence was omitted, the first line under `Truncation` must instead be
`present: <what was omitted and why>`. Every section is required and non-empty.
The runner rejects secret-like text, malformed packets, 24,001 characters, and
silent truncation before any paid call.

## Enforced Runtime Boundary

The command starts Claude with:

- the exact configured model and effort;
- safe mode, Chrome disabled, and an empty tools list;
- `plan` permission mode;
- the complete prompt on stdin rather than process-visible argv;
- stream JSON with visible-text checkpointing; only a complete, valid JSON event
  resets the no-event timer;
- 10-minute wall timeout and 3-minute no-event timeout, with the child isolated
  in a process group and terminated as SIGTERM then SIGKILL;
- hard caps of 1 MiB per incomplete stream line, 100,000 visible characters,
  and 10 MiB for the sanitized event log;
- a `$2` default `--max-budget-usd` enforced by Claude CLI.

The dollar cap is not local mid-stream telemetry: Claude CLI owns enforcement,
and total cost may appear only in its final result event. Partner records that
fact as `budget_enforced_by: claude_cli`; it does not claim to know a live
cumulative cost it never received.

## Output Contract

A zero CLI exit and `is_error=false` are both required but not sufficient. The
visible result must start with `# Plan Checkpoint` and contain these non-empty
level-two sections in order:

1. `Goal`
2. `Non-goals`
3. `Current-State Evidence`
4. `File Scope`
5. `Steps`
6. `Risks`
7. `Acceptance Checks` (optionally suffixed with `(binary)`)
8. `Rollback`

A conversational preamble, empty result, missing section, reordered section, or
empty section is a `protocol_error`. The runner preserves the visible text in
the checkpoint and writes recovery instructions, but does not create a plan
file. A nominal success must also report the requested session id and exact
configured model; observed values are persisted in metadata and mismatches fail
closed.

## Artifacts

Each run gets an immutable directory under
`.partner/runs/<run-id>/`:

```text
events.jsonl    Sanitized event envelope; no thinking content or packet copy
checkpoint.md   Visible text received so far; equals the plan on success
metadata.json   Configured/observed identity, limits, result, cost, runner/packet hashes, and failure class
recovery.md     Same-session resume command and explicit no-fallback notice
```

Successful plans are atomically created at `.partner/plans/<run-id>.md`.
Existing run directories and plan files are never overwritten, including when
two runs race for the same explicit `--output`.

## Recovery

On idle, wall timeout, API error, budget stop, authentication failure, or any
attempted tool use, the runner exits non-zero and writes `recovery.md`. Resume
the recorded session first. A different configured role may be used only after
explicit user approval; Partner never changes it automatically.

The existing one-line setup smoke still proves only that an identity can start.
For release claims, run at least three repository-scale near-limit attempts,
including a valid fresh plan and a valid same-session recovery. Inspect every
failure rather than requiring upstream availability to look perfect, and bind
the final fresh candidate to the reviewed runner and packet hashes.
