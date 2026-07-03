# Partner Memory Protocol (wrap-up phase)

Run this at the end of every non-trivial Partner session, both directions.
The point is that the *next* split decision starts smarter: which task
types Codex handles well, which effort levels fit, where rework happened.

## What to Record

One compact record per session, structured:

- repo + one-line task summary
- what was delegated to Codex vs kept in Claude, and why
- per delegated task type: quality outcome (accepted first pass /
  rework rounds / taken back)
- effort level used and whether it fit
- any monitoring anomaly and what fixed it

Skip sessions with nothing new to say — memory hygiene beats volume.

## Layers (write in this order, skip layers that are unavailable)

1. **claude-mem (automatic)** — if the claude-mem plugin is installed, the
   SessionEnd hook captures a semantic summary on its own. No action
   needed; do not duplicate its raw event capture by hand.
2. **mem0 MCP (active, cross-tool)** — when mem0 tools are available, call
   its add-memory tool with the structured record above, tagged
   `partner-skill` plus the repo name. Both Claude Code and Codex read the
   same mem0 store, so this is the shared cross-agent layer.
3. **Claude Code auto-memory** — persist durable *routing* lessons (for
   example "Codex writes vitest suites well at effort=high, zero rework")
   as normal auto-memory notes, following the built-in rules: one fact per
   note, update rather than duplicate, delete wrong notes.
4. **Codex rollout memory (passive)** — Codex's `[memories]` system absorbs
   the delegated sessions automatically. Make it useful by always ending
   delegation packets with the lessons-learned instruction (see
   `references/fable5-principles.md`, Output Discipline), so the rollout
   contains an explicit distillation, not just a transcript.

## Static Layer Reminder

Facts that every future session must see unconditionally do not belong in
memory stores: put them in the repo's `CLAUDE.md` (Claude Code) and
`AGENTS.md` (Codex) instead — architecture, commands, conventions. Memory
layers are for experience; instruction files are for law.
