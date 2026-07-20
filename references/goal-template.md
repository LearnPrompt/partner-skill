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
| id | owner (executes on) | role (capability tier) | task | acceptance | effort | status | jobId |
|----|----------------------|-------------------------|------|------------|--------|--------|-------|
| T1 | claude | deep_reasoner | ... | ... | - | in_progress | - |
| T2 | codex | fast_worker | ... | [check command that must pass] | high | delegated | job-... |

status: pending | in_progress | delegated | review | rework-1 | rework-2 | taken-back | done

## Anomalies
[none, or one line per monitoring anomaly: job, what happened, action taken]

## Notes
[Integration decisions and takebacks worth carrying into the receipt and memory.]
```

`owner` and `role` are independent axes, decided separately for every row —
neither implies the other:

- **`owner`** = which channel bills for and executes this task: `claude`
  (this session, Claude API meter) or `codex` (a `delegate-codex.sh`
  background job, Codex subscription meter). This is the cost-split
  decision Direction B exists for — Claude stays the driver (plan, split,
  review) while `codex`-owned rows push the actual grunt work off the
  Claude meter.
- **`role`** = which config-defined model/effort tier answers the call once
  it runs, on *either* side of the owner split: `deep_reasoner` (ambiguous,
  high-stakes, wrong-premise-is-expensive work) or `fast_worker`
  (mechanical, spec-complete work). A `codex`-owned row is not automatically
  `fast_worker` — a hard Codex-side diagnosis still wants `deep_reasoner`'s
  tier; a routine Claude-owned row can be `fast_worker` too.

Worked example: a task to reconfigure a site's i18n routing (getting the
locale scheme wrong would silently break every existing URL) is
`owner: codex` (push the edit-and-build-verify loop off the Claude meter)
**and** `role: deep_reasoner` (the wrong-premise-late risk justifies the
expensive tier) — both non-default choices on independent axes, in the
same row.

Rules:

- One row per task; `jobId` comes from `delegate-codex.sh submit`.
- `acceptance` must be verifiable (a command to run, a behavior to observe),
  not a vibe. It is what Phase 4 reviews against.
- The `/loop` monitoring prompt reads this file first, so keep statuses
  current — stale rows cause duplicate delegation.
