# Claude-Driven Partner Flow (Direction B)

Use this flow when the skill is loaded inside Claude Code and the user asks
Claude to split work with Codex ("双向搭子", "分工给 codex", "让 codex 做",
"codex 后台跑"). Claude Code is the driver: it plans, delegates
quota-pressure work to Codex (subscription billing), monitors the background
jobs, and quality-gates everything before accepting it. The goal is saving
Claude API spend without lowering quality — the full-review gate in Phase 4
is what makes that claim honest.

All helper scripts live in `$PARTNER_DIR` (see Tool Location in `SKILL.md`).
Job state lives under `<repo>/.partner/jobs/`.

## Phase 0 — Preflight

- Confirm the Codex CLI: `codex --version`. If missing, stop and tell the
  user this flow needs the Codex CLI installed and authenticated.
- Check the target repo's `AGENTS.md` for the line
  `DO NOT send optional commentary`. If absent, ask the user once whether to
  append it (it reduces Codex filler output and keeps its replies dense).
  Never edit the user's repo files silently.
- Run `git status --short` and note pre-existing dirt so Codex's diff can be
  isolated later.

## Phase 1 — Plan and Split (goal file)

- Refine the user's request into a concrete plan, then write
  `<repo>/.partner/goal.md` (template: `references/goal-template.md`): the
  overall goal as one why-forward sentence, a task table, and the checkpoint
  rule from `references/fable5-principles.md`.
- Split tasks with this default routing:
  - To Codex (subscription quota): mechanical refactors, test writing,
    wide read-only codebase scans, doc generation, boilerplate for isolated
    modules, batch migrations.
  - Keep in Claude (API, quality-critical): architecture, the split decision
    itself, cross-module integration, security/correctness-critical paths,
    final acceptance.
- Adversarial gate: run the idea-king adversarial review (the `idea-king`
  skill, or `references/../idea-king/SKILL.md` content inline) against the
  split. Two questions it must answer: does each Codex task really not need
  the expensive model, and does the integration cost of the split boundary
  eat the savings? Fix the split before delegating.

## Phase 2 — Delegate

- Build each Codex prompt from the "Claude → Codex Delegation Packet" in
  `references/handoff-template.md`: why-forward context, one-sentence task,
  verifiable acceptance criteria, scope constraints, and the fixed output
  rules (no optional commentary; lessons learned at the end).
- Submit as a background job (default effort `high` — the user is on a
  subscription plan, do not economize on effort at the cost of rework):

```bash
prompt=$(mktemp)
# ... write the delegation packet into "$prompt" ...
bash "$PARTNER_DIR/scripts/delegate-codex.sh" submit \
  --repo "$REPO" --prompt-file "$prompt" --label <task-id> --effort high
```

- Use `--read-only` for scan/review jobs that must not modify the repo.
- Record the returned jobId in the goal file's task row. Independent tasks
  can be submitted in parallel.

## Phase 3 — Monitor (loop)

- Short single job (expected under ~5 minutes): block on it —
  `bash "$PARTNER_DIR/scripts/delegate-codex.sh" status <jobId> --repo "$REPO" --wait --timeout 300`.
- Long or multiple jobs: set up the built-in `/loop` skill at a 5-minute
  interval with a prompt like: read `.partner/goal.md`, run
  `delegate-codex.sh status` for every running jobId (tail the job's
  `log.jsonl` for the last event), update task statuses in the goal file,
  and when no job is left running, stop the loop and continue with Phase 4.
- A job stuck with no new JSONL events for two consecutive ticks, or a
  `status` of FAILED, is a monitoring anomaly: cancel it, read
  `stderr.log`, and either resubmit with a corrected prompt or take the
  task back into Claude. Record the anomaly for the receipt.

## Phase 4 — Full Review Gate

- Collect each finished job:
  `bash "$PARTNER_DIR/scripts/delegate-codex.sh" result <jobId> --repo "$REPO"`.
- Claude reviews the complete diff itself — `git diff` (scoped to the files
  the job touched), plus the fastest relevant check. This is a full review
  by default, not a sample. Do not accept work you have not read.
- Findings? Send one bounded fix round back to the same Codex session:

```bash
bash "$PARTNER_DIR/scripts/delegate-codex.sh" resume <jobId> \
  --repo "$REPO" --prompt-file <fix-notes>
```

- Maximum two fix rounds per task. Still failing after that: take the task
  back and finish it in Claude; note the takeback in the goal file and
  receipt. Optionally run the gstack `/codex` review on the final combined
  diff as an independent third-party gate.

## Phase 5 — Wrap Up

- Mark tasks done in `.partner/goal.md`; stop any remaining `/loop`.
- Emit the Partner Session Receipt with `direction: claude-driven` and
  `codex_jobs: <count>`; in this direction `claude_session` refers to the
  current session and `new_claude_p_sessions` is normally `0`.
- Run the memory protocol in `references/memory-protocol.md`: what got
  delegated, how Codex performed per task type, rework rounds, and effort
  fit — so the next split decision starts smarter.
