# Plan → Goal → PR → Verification (Direction B, opt-in)

This is the escalated protocol for Direction B when the user asks for the
full pipeline, not the default lightweight flow. Everything in
`references/claude-driven.md` still applies; this file adds a Delivery
phase and the authorization discipline that lets it run unattended up to a
hard stop.

## Trigger Grading

- **One-off small change** (a bug fix, a small file, an isolated task):
  stay on the fast path in `references/claude-driven.md`. Do not create
  `.partner/goal.md` for this — a goal file for a five-line fix is
  ceremony, not safety.
- **User says "完整协议" / "PR 交付" / "目标模式"** (or the equivalent in
  English — "full protocol", "deliver a PR", "goal mode"): run this file's
  four stages below.
- **Recurring, independently-verifiable work the user wants to self-run**
  (a nightly sweep, a repeating audit): hand off to the `loop-engineering`
  skill itself instead of stretching this protocol to fit. This file and
  that skill interlink; neither absorbs the other.

The `ordinary-pr-no-trigger` test case exists specifically to keep small
changes off this path — escalating a one-line fix into a full Goal/PR cycle
is a cost, not a safety margin.

## Stage 1 — Plan

- Run with plan-mode permissions; read the real repo, not just the request.
- Output: goal, non-goals, current-state evidence (file:line, not vibes),
  file scope, phases, risks, acceptance criteria, rollback plan, and open
  decisions the user needs to make.
- Run the idea-king adversarial gate on the plan, including its
  clarify-to-95% pre-verdict protocol — do not let a plan through on a
  guessed understanding of the need. Once idea-king ships it, the
  *executing* host reviews it independently; the same agent must not be the
  only maker and the only judge of its own plan.
- Plan stage never touches files. No branch, no worktree, no commit.

## Stage 2 — Goal

- Write `<repo>/.partner/goal.md` from `references/goal-template.md`,
  including its `## Delivery` section (branch/worktree, pr, ci, preview,
  live, authorization). The task table's `status` enum is unchanged from
  the base template — do not add or rename values; `/loop` monitoring's
  stop rule and older goal.md copies depend on the existing enum. Use
  `scripts/goal-sync.py read`/`write --expect-sha256 <hash>` for the write
  so a concurrent update from the other host aborts your write instead of
  being silently lost.
- Every `done_when` gets the anti-Goodhart clause next to it: the check
  must not be satisfiable by deleting tests, skipping steps, or weakening
  the acceptance bar. A done_when that a maker could trivially "pass" by
  making the check meaningless is not a valid done_when — fix the check,
  not the standard.
- `done_when` and `hard_stops` are orthogonal: reaching every done_when
  condition never implies permission to cross a hard stop. They compose by
  AND, not by either substituting for the other.

## Stage 3 — PR (runs to merge-ready, then stops)

Once the user has authorized the full protocol (see Authorization below),
execute without re-asking, up through "merge-ready PR + preview verified":

1. Create the branch or worktree recorded in the goal file's Delivery
   section.
2. Implement each task, delegating per the routing in
   `references/claude-driven.md`.
3. Run the Verify Ladder (Stage 4) after each risky change, not just once
   at the end.
4. Push the task branch, open or update the PR, record its URL in
   `Delivery.pr`.
5. Wait for CI; on failure, read the actual CI log (not just re-run
   locally) and fix; record the CI status in `Delivery.ci`.
6. Verify the preview deployment if the repo has one; record it in
   `Delivery.preview`.

Stop here. The following are each an independent hard stop — each one
needs its own fresh imperative sentence from the user, not implied by
"finish it" or by an earlier authorization for a different action:

- Merge into the target branch.
- Anything touching production (deploy, promote, migrate live data).
- Creating a release tag.
- Force-push of any kind.
- Deleting a branch, file, or resource that isn't scratch this session created.
- A destructive or irreversible migration.
- Any external publish (registry, marketplace, announcement, visibility change).

Record each authorization actually given, verbatim intent, in the goal
file's `Delivery.authorization` field — this is the audit trail for why an
otherwise-blocked action ran.

## Stage 4 — Verification (Verify Ladder)

Fast feedback first, escalate only as needed:

1. The single targeted test for the change just made.
2. Lint / typecheck.
3. The affected module's test suite.
4. Full test suite / build.
5. Diff-against-acceptance: re-read `.partner/goal.md`'s acceptance
   criteria and the actual diff — not the maker's self-report of what it
   did. A checker who only reads the diff confidently redefines the spec
   as "consistent with what changed" and misses undone tasks (see
   `references/fable5-principles.md`'s Superpowers 6 citation).
6. Secret scan.
7. Migration check, if the change touches schema or persisted state.

Rules that apply throughout:

- Only run commands the target repo itself documents (package.json
  scripts, Makefile targets, CI config it already has). Never invent a
  CI/deploy command that doesn't exist in the repo; if the repo has none
  for a rung, mark that rung `n/a` and say so — do not skip silently.
- CI green is not the same claim as "the feature works." Preview is not
  production. Do not conflate any of the three.
- Once the user has authorized merge/deploy, verify the actual production
  page or API after it happens — do not report success from the deploy
  log alone.
- Final report is layered, one line each: local checks / branch+PR / CI /
  preview / production / remaining risk. A layer that was not reached says
  so explicitly (`not reached`), never silently omitted.

## Authorization Discipline

- A question from the user ("should I open a PR?") is a status query, not
  a green light — answer it, do not act on it.
- One imperative sentence authorizes one action. "Ship it" after a plan
  review authorizes Stage 3 up to merge-ready; it does not authorize merge,
  and a later "looks good" does not either — merge needs its own sentence.
- If unsure whether an instruction covers a hard-stop action, treat it as
  not covering it and ask.
