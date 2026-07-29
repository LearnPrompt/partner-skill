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
  rule from `references/fable5-principles.md`. If the repo may have a
  second host writing the same goal.md concurrently, use
  `scripts/goal-sync.py read`/`write --expect-sha256 <hash>` instead of
  editing the file directly — it aborts instead of silently clobbering the
  other host's update.
- Split tasks by making one judgment per row — which capability does this
  work need (see the identity definitions in `references/goal-template.md`):
  - `fast_worker` for mechanical, spec-complete work (refactors, test
    writing, wide read-only scans, doc generation, boilerplate, batch
    migrations) — the bulk of delegable work.
  - `deep_reasoner` for ambiguous, wrong-premise-is-expensive work (a hard
    diagnosis, a config change whose wrong variant silently breaks things).
  - identity `-` for what the driver keeps inline: architecture, the split
    decision itself, cross-task integration, security/correctness-critical
    paths, final acceptance. Never route these to a cheaper identity to
    save money, and never burn the driver's seat on mechanical work.
  Which CLI executes and which meter bills follows from the identity's
  configured `backend` (`搭子，配置`), not from a separate per-task choice.
  Two escape hatches remain for edge cases: a one-shot Codex subagent
  (e.g. a rescue agent) for a stuck step needing a second diagnosis with
  no durable state, and a raw Task-tool subagent when no Partner identity
  fits — billing notes for both in `references/fable5-principles.md`.
- Adversarial gate: run the idea-king adversarial review (the `idea-king`
  skill, or `references/../idea-king/SKILL.md` content inline) against the
  split. It must answer three questions: does each delegated task really
  not need the expensive tier, does the integration cost of the split
  boundary eat the savings, and does each row's identity match the work's
  actual stakes (with a reason it is not a more expensive one). Fix the
  split before delegating; its `分工 (Assignment)` section is the
  corrected task→identity mapping you act on.

## Sub Agent Routing

This lookup applies **only to identities whose configured `backend` is
`claude`** — an identity with `backend = codex` never enters it: that work
goes through `delegate-codex.sh` (Phase 2), and spawning a Task subagent
for it would silently swap in the wrong vendor and meter. For a
claude-backend identity, resolve *which* agent definition to spawn with
this three-level lookup, in order:

1. **`partner-*` namespaced agent** — if `搭子，配置` has generated
   `partner-deep-reasoner` / `partner-fast-worker` / `partner-arbiter`
   (project or global scope; check
   `python3 "$PARTNER_DIR/scripts/partner-config.py" --host claude_code resolve`
   for the configured identity, or just try spawning the namespaced agent),
   use it. Its model/effort came from the user's own setup choice.
2. **The user's own similarly-named agent** — if no `partner-*` agent exists
   but the user has their own `deep-reasoner.md` / `fast-worker.md` (or an
   agent whose description clearly matches the identity), use it as-is.
   Never rename, edit, or treat it as if it were partner-managed.
3. **Generic `Task` tool** — no matching agent either way: spawn a plain
   Task-tool subagent with the identity described in the prompt. This is the
   fallback, not a signal that setup is missing something the task needs.

A repo with no `搭子，配置` run yet simply falls through to level 3 every
time; that is normal, not broken.

## Arbiter Protocol — 盲解仲裁

For contentious or high-stakes calls — the driver judges the answer
disputable, or the user says 仲裁 / 有争议 / second opinion — do not settle
for one solver's answer:

1. Send the **same problem, verbatim** to both `deep_reasoner` and
   `arbiter`, each through its own configured backend (subagent spawn or
   `delegate-codex.sh --host claude_code --role arbiter`).
2. **Contamination rule**: neither packet may contain the other solver's
   answer, conclusion, or any leaning hint ("X thinks A, verify it" is
   already contaminated). Blind means blind — a contaminated run silently
   produces fake agreement and must be rerun, not patched.
3. Compare the two answers. Agreement → adopt, note dual-verified.
   Disagreement → the driver rules, and records the point of divergence
   plus the ruling's reasoning in the receipt (both solvers appear in
   `roles_used`; the divergence goes in the report/Notes).
4. The blind check is strongest when arbiter and deep_reasoner run on
   different vendors (the wizard's default presets guarantee this); if the
   config has them same-vendor, the protocol still runs but the receipt
   notes `same-vendor` so the weaker independence is visible.

This is distinct from the idea-king gate: 点子王 attacks a *plan* you
already have; the arbiter independently *solves the same problem* with no
knowledge of the first answer.

## Phase 2 — Delegate

- Build each Codex prompt from the "Claude → Codex Delegation Packet" in
  `references/handoff-template.md`: why-forward context, one-sentence task,
  verifiable acceptance criteria, scope constraints, and the fixed output
  rules (no optional commentary; lessons learned at the end).
- Submit as a background job, passing the row's identity so backend, model,
  and effort resolve from `搭子，配置`'s config. `--host claude_code` reads
  the driver's own routing table (explicit `--model`/`--effort` still wins
  per field if a specific task genuinely needs an override):

```bash
prompt=$(mktemp)
# ... write the delegation packet into "$prompt" ...
bash "$PARTNER_DIR/scripts/delegate-codex.sh" submit \
  --repo "$REPO" --prompt-file "$prompt" --label <task-id> \
  --host claude_code --role <identity>
```

The tool fail-closes on both misconfigurations: no Partner config yet →
clear error (run `搭子，配置` first, or fall back to an explicit `--effort`
for this one job and note it in `Notes`); identity configured with
`backend = claude` → refusal with a pointer to spawn the `partner-<identity>`
subagent instead — this is the guard against silently running a
claude-backend identity on the wrong vendor.

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
- Review against the acceptance criteria in `.partner/goal.md`, not against
  the diff alone. A reviewer given only the diff confidently redefines the
  spec as "internally consistent with what changed" and misses tasks that
  were never done — in Superpowers 6, diff-only reviewers caught 0 of 5
  missing task briefs. Re-read each task's brief, then ask "does this diff
  satisfy that brief," not just "is this diff self-consistent."
- Findings? Send one bounded fix round back to the same Codex session:

```bash
bash "$PARTNER_DIR/scripts/delegate-codex.sh" resume <jobId> \
  --repo "$REPO" --prompt-file <fix-notes>
```

- Maximum two fix rounds per task. Still failing after that: take the task
  back and finish it in Claude; note the takeback in the goal file and
  receipt. Optionally run the gstack `/codex` review on the final combined
  diff as an independent third-party gate.

## Phase 4.5 — Delivery (opt-in, `references/goal-to-pr.md`)

Only runs when the user asked for the full "完整协议 / PR 交付 / 目标模式"
protocol (see Trigger Grading in `references/goal-to-pr.md`) and has
authorized it via a Goal Packet (`references/handoff-template.md`). Skip
this phase entirely on the default lightweight flow above.

- Follow Stage 3 (PR) and Stage 4 (Verify Ladder) in
  `references/goal-to-pr.md`: branch/worktree, implement, verify, push,
  open/update PR, wait for and fix CI, verify preview.
- Stop at merge-ready + preview verified. Merge, production, tags,
  force-push, deletion, destructive migration, and external publish are
  each an independent hard stop — each needs its own fresh imperative
  sentence, recorded in the goal file's `Delivery.authorization` field.
- Update `.partner/goal.md`'s `## Delivery` section as each field becomes
  known (branch/worktree, pr, ci, preview, live).

## Phase 5 — Wrap Up

- Mark tasks done in `.partner/goal.md`; stop any remaining `/loop`.
- Emit the Partner Session Receipt with `direction: claude-driven` and
  `codex_jobs: <count>`; in this direction `claude_session` refers to the
  current session and `new_claude_p_sessions` is normally `0`. Set `host`,
  `scope`, and `config_source` from `partner-config.py resolve` (or
  `partner-setup.py --status`), and build `roles_used` from the roles this
  run actually invoked: each `delegate-codex.sh` job's `meta` file has
  `role`/`model`/`effort`/`model_source`/`effort_source`, and
  `partner-config.py resolve` has each role's `verified`/`verified_at`. List
  a role even when `verified` is `false` — never guess it true.
- Run the memory protocol in `references/memory-protocol.md`: what got
  delegated, how Codex performed per task type, rework rounds, and effort
  fit — so the next split decision starts smarter.
