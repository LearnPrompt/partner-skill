# Partner Setup Wizard (搭子，配置)

First-run configuration for the dual-host Partner. Triggered by "搭子，配置"
(or when a Partner flow needs a role that has no configuration yet). The
wizard is a *conversation rendered by the current host*; every actual state
change goes through `python3 "$PARTNER_DIR/scripts/partner-setup.py"` — one
engine, no second implementation. Never edit `.partner/config.toml` by hand
in this flow.

## Render paths

Pick exactly one, by host:

- **Claude Code**: ask each screen with the native question UI
  (AskUserQuestion), one screen at a time, options prefilled from the
  engine's detection output.
- **Codex**: ask the same screens conversationally — one question per turn,
  each with a recommended answer the user can just confirm.
- **No interactive user (plain CLI)**: run
  `python3 "$PARTNER_DIR/scripts/partner-setup.py" --interactive` in the
  terminal and step back; do not re-implement the questions.

## Screens (balanced path ≤3 steps)

1. **Detection (display, don't ask)** — run `partner-setup.py --status` and
   show: current host, both CLIs' availability (`claude` and `codex` on
   PATH — an identity can only use a backend whose CLI is installed),
   existing config (if any), and detected model/effort values with their
   source tag (`detected` from host config | `built-in` alias |
   `custom (unverified)`). If a config with another host's namespace
   already exists, jump to *Second host joining* below.
2. **Work mode** — one choice: 均衡 balanced (default) / 质量 quality /
   成本 cost / 自定义 custom. Each preset carries a full identity matrix —
   three identities (deep_reasoner / fast_worker / arbiter), each with its
   own backend (which CLI executes), model, and effort, freely mixed across
   vendors. Only custom expands the per-identity backend → model → effort
   questions (one identity per screen). Codex-backend models are never
   offered from a hardcoded list: offer the detected value or ask for an
   explicit string. If arbiter and deep_reasoner end up on the same
   backend, warn that the blind cross-check loses independence — allow it,
   but say it.
3. **Scope & writes** — scope: 当前项目 project (default) / 所有项目
   global. Write items: generate Claude agent files ☑ (only for identities
   whose backend is claude) / persistent routing block ☐ (default OFF —
   plain "no" is the right answer unless the user asked for always-on
   routing rules).

Then, without asking further questions:

4. **Preview** — `partner-setup.py --preview ...` with the collected
   choices; show the exact file paths and diffs to the user; one
   confirm/cancel question.
5. **Apply** — same arguments with `--apply`. Report exactly what was
   written. If the repo-scope config is not git-ignored, the engine handles
   the exclude choice (default: one line in `.git/info/exclude`); relay its
   report.
6. **Smoke test (recommended, skippable, never blocking)** —
   `partner-setup.py --smoke`. Codex-backend identities verify through the
   delegate dry-run chain and get `verified=true` written back.
   Claude-backend agent files are only visible to *new* sessions: the
   engine reports `needs_new_session`; tell the user verification completes
   automatically on first real use in a fresh session. Never claim verified
   without engine evidence.
7. Point the user at "搭子，试跑" (`references/tryout.md`) — the real
   end-to-end proof pass where every identity runs a micro-task and a
   report shows each one live on its configured model. Close with a normal
   Partner Session Receipt.

## Second host joining (incremental merge)

When a config already exists with the other host's namespace, show a short
summary of the existing host's roles, then one three-way choice:

- **接入并添加本宿主配置** (default) — continue the wizard; only
  `hosts.<self>` sections are added, the other host's bytes are untouched
  (show the engine preview as proof).
- **仅用共享 Goal/Loop，不生成配置** — stop; nothing is written.
- **返回，不做修改** — stop.

Never re-run an overwrite-style initialization on an existing config.

## Existing user agents (claude_code host)

If the user already has their own `deep-reasoner.md` / `fast-worker.md`
agents, the generated files stay namespaced (`partner-deep-reasoner`,
`partner-fast-worker`) and never touch user files. When the engine refuses
a path (exists, not in the manifest), offer the three-way:

- **导入现有设置** — read the user agent's model as the initial value, then
  still write only `partner-*` files.
- **生成 namespaced partner-\*** (default) — skip the conflicting path,
  write the rest.
- **跳过** — no agent files; config only.

## Rules

- One question per screen; every question ships with a recommended answer.
- Values the engine detected are shown, not re-asked.
- Preview before every write; the user sees paths + diffs, not a summary.
- No silent fallback: if a model/effort combination fails at apply or
  smoke, surface the engine's original error and offer to re-run setup —
  never swap models quietly.
- `--rollback` restores the last-apply backup; offer it if the user is
  unhappy right after an apply.
- User-owned files (their agents, hand-written CLAUDE.md/AGENTS.md content)
  are read-only to this flow; the managed routing block writes only inside
  its own markers and only when explicitly enabled.

## Uninstall

`python3 "$PARTNER_DIR/scripts/partner-setup.py" --uninstall --host <host> [--remove-config] [--dry-run]`

Removes only what this host generated: `partner-*` agent files whose hash
still matches `.partner/.generated-manifest` (a file the user hand-edited
since generation is left in place and reported as skipped, never deleted),
and a structurally valid managed routing block. Config is untouched unless
`--remove-config` is passed, which clears only `hosts.<host>.roles` — the
other host's section, top-level fields, and `[routing]` are byte-preserved.
`--dry-run` reports what would be removed without writing anything.
