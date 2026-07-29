# Partner Goal File Template

The Claude-driven flow (Direction B) persists its plan and delegation state
in `<repo>/.partner/goal.md` so a `/loop` tick, a resumed session, or the
other agent can pick up the state without rebuilding context. Update it in
place as jobs progress; do not create parallel copies.

```markdown
# Partner Goal

## Goal
[One why-forward sentence: working on X for Y, so that Z. Done when: <verifiable completion condition>. Anti-Goodhart: the done_when check must not be satisfiable by deleting tests, skipping steps, or weakening the acceptance bar — if it can be, fix the check, not the standard.]

## Checkpoint Rule
Pause for the user only on: a destructive or irreversible action, a real
scope change, or something only the user can provide. Otherwise keep going
and report when done.

## Delivery
[Only used under the full Plan→Goal→PR→Verification protocol; references/goal-to-pr.md. Leave as "n/a" on the lightweight path.]
- branch/worktree: <name or path, or n/a>
- pr: <URL, or n/a>
- ci: <status, or n/a>
- preview: <URL/status, or n/a>
- live: <status, or n/a — production/deploy state, verified independently of ci/preview>
- authorization: <one line per hard-stop action actually authorized, verbatim user intent, or none yet>

## Tasks
| id | identity | task | acceptance | effort | status | jobId |
|----|----------|------|------------|--------|--------|-------|
| T1 | deep_reasoner | ... | ... | - | in_progress | - |
| T2 | fast_worker | ... | [check command that must pass] | high | delegated | job-... |

status: pending | in_progress | delegated | review | rework-1 | rework-2 | taken-back | done

## Anomalies
[none, or one line per monitoring anomaly: job, what happened, action taken]

## Notes
[Integration decisions and takebacks worth carrying into the receipt and memory.]
```

Splitting a task means making **one** judgment per row: which capability
does this work need? The three identities are defined by `搭子，配置`, each
carrying its own backend (which CLI executes and which meter bills), model,
and effort — so picking the identity picks the execution channel
automatically; there is no separate "owner" decision:

- **`deep_reasoner`** — architecture, ambiguous requirements, root-cause
  diagnosis, anything where a wrong premise in step one is expensive to
  discover late.
- **`fast_worker`** — mechanical, well-scoped, specification-complete work
  where the acceptance criteria alone are enough to verify correctness.
- **`arbiter`** — the blind second solver for contentious or high-stakes
  calls; normally invoked by the Arbiter protocol in
  `references/claude-driven.md`, not assigned routine rows of its own.

Rows the driver keeps for itself — the split decision, cross-task
integration, final acceptance — take identity `-`: they run inline in the
driving session and never spawn or delegate.

At execution time, resolve the identity's config
(`partner-config.py resolve`): `backend = codex` → submit through
`delegate-codex.sh --host <driver> --role <identity>` (Codex subscription
meter); `backend = claude` → spawn the `partner-<identity>` subagent
(Claude API meter). The same identity can point at either vendor — that
mapping lives in `.partner/config.toml`, not in this table.

Rules:

- One row per task; `jobId` comes from `delegate-codex.sh submit` (rows
  whose identity resolves to a claude backend keep `-`).
- `acceptance` must be verifiable (a command to run, a behavior to observe),
  not a vibe. It is what Phase 4 reviews against.
- The `/loop` monitoring prompt reads this file first, so keep statuses
  current — stale rows cause duplicate delegation.
