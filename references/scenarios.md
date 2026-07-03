# Partner Scenario Profiles

The default flow in `SKILL.md` assumes a small-to-medium, UI-leaning task in a
git repository. These profiles say what changes when the task does not fit
that picture. Everything not mentioned here follows the default flow, and the
core split never changes: Claude Code plans/polishes/reviews, Codex
implements/verifies, one session is reused, and the run ends with a receipt.

## Review-Only

The user only wants the current diff reviewed and fixed.

- Skip the planning phase; do not send `/goal`.
- Start (or reuse) one Claude Code session directly for `/codex:review`.
- Codex fixes blocking findings and reruns checks; style-only findings are Codex's call.
- Receipt: `phase: review`; `claude_session_reused` reflects whether an existing session was picked up.

## Debugging / Incident

The goal is a diagnosis, not a feature.

- Invert the loop: Claude Code proposes ranked hypotheses; Codex reproduces, instruments, and confirms or kills each one in the repo.
- Send Claude reproduction output and failing-check evidence, not file dumps.
- The polish phase becomes "harden the fix": regression test, error message quality, log clarity.
- Stop condition is a reproduced-then-fixed failing case, not "code looks right".

## Non-UI Task (Backend, Scripts, Data)

There is no visual surface, but the polish phase still exists — redefined:

- Polish targets: API shape and naming, error messages, edge-case behavior, log/output quality, docs and help text.
- Ask Claude for prioritized findings on those axes instead of visual critique.
- Never skip polish just because there is no UI; skip it only when the user asks for the minimal loop.

## Non-Git Directory

`git status` is the default grounding step, but some targets are plain folders.

- Replace git evidence with a bounded file inventory (see `NOT_GIT_REPO` in `references/monitoring.md`); `"$PARTNER_DIR/scripts/make-handoff.sh"` does this automatically.
- Verification relies on checks and file diffs by timestamp/content, so state before/after inventories explicitly.
- Receipt: note `non-git target` under `checks` or `anomalies` so the evidence level is transparent.

## Monorepo

Repo-wide diffs drown the handoff in unrelated noise.

- Scope every git command to the package: `git status --short -- <path>`, `git diff --stat -- <path>`.
- Name the package path in the handoff Task line; Claude should not reason about sibling packages.
- Run the package-local check (workspace script) rather than the repo-wide suite when iterating; run the wide suite once before the final receipt.

## Large Or Multi-Day Task

One session will not survive the whole task, so persist state instead of hoping.

- Write the accepted plan to `.partner/plan.md` as soon as Claude produces it.
- Save every handoff with `bash "$PARTNER_DIR/scripts/make-handoff.sh" --save`; save the final receipt with `make-receipt.py --save`.
- When the session is lost, cold-start the replacement with `plan.md` + the newest handoff only — this is the bounded payload, already written.
- Receipt: count each replacement session honestly (`claude_session_reused: no` for the first pass after a loss) and say why in `anomalies`.
