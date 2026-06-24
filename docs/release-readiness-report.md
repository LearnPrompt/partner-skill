# Partner Release Readiness Report

Date: 2026-06-25

Skill: `partner-skill` / 搭子.skill (Partner)

Slogan: 我的 Claude Code 和 Codex 天下第一好。

## Verdict

Partner is now a public-ready release candidate as a workflow skill, with one caveat: the repository is still private and no public release/tag has been created. Publication is a separate user-authorized action.

## Office Hours Lens

Six forcing questions:

1. Demand reality: users already switch between Claude Code and Codex to save cost and improve quality.
2. Status quo: manual copy-paste handoffs, unclear permissions, and weak monitoring.
3. Desperate specificity: useful when the task is UI-heavy, feature-heavy, or long-context, and Claude Code API cost matters.
4. Narrowest wedge: one same-session Claude Code loop: plan, polish, review; Codex implements and verifies.
5. Observation: the first `skill-inventory` run exposed a real stuck `/codex:review` subprocess, proving monitoring matters.
6. Future fit: as agent tools multiply, explicit collaboration protocols beat ad hoc agent switching.

## Brainstorming Lens

Explored positioning options:

- Relay/orchestrator: accurate but forgettable.
- Duet: good collaboration metaphor but less native in Chinese.
- 搭子.skill / Partner: strongest memory hook and most user-speakable framing.

Chosen positioning:

> Give Codex a Claude Code partner.

## Luban Lens

Before this pass:

- Strong SKILL.md workflow.
- Weak public README.
- No installer.
- No publish readiness script.
- No visible example/miniloop.
- No explicit validation ratchet.

After this pass:

- README has install, triggers, evidence, example, safety, file map, and release checklist.
- `install.sh` supports Codex, Claude Code, Agents, and all targets.
- `scripts/check-skill-repo.sh` verifies package structure, prompt schema, identity, bare `搭子` trigger, showcase asset, secret scan, and high-risk command mentions.
- `references/handoff-template.md` encodes bounded Claude Code handoff.
- `references/darwin-ratchet.md` encodes validation-gated edits.
- `references/monitoring.md` now prefers same-session recovery before expensive fresh Claude sessions.
- `examples/skill-inventory-miniloop.md` documents the first real Partner run.
- `assets/showcase.gif` gives GitHub visitors a first-screen workflow preview.

Estimated score:

```text
Before: 80 / 100
After: 95 / 100
```

Remaining gap before public launch:

- Run one more full UI-oriented loop where Claude Code performs the polish pass and `/codex:review` completes cleanly.
- Consider a public `v0.1.0` tag only after the repository visibility decision.

## Darwin Lens

Edited dimension:

```text
Release entrypoint and showcase assets
```

Validation gate:

```bash
bash scripts/check-skill-repo.sh .
jq -e 'type == "array" and length == 8 and all(.[]; has("id") and has("prompt") and has("expected_behavior") and has("must_not"))' test-prompts.json
bash install.sh --target codex --dry-run
bash install.sh --target claude --dry-run
python3 scripts/generate-showcase-gif.py
file assets/showcase.gif
```

Result:

```text
PASS package readiness
PASS prompt schema
PASS installer dry runs
PASS showcase GIF exists and is referenced
WARN high-risk command text found only in safety warnings
```

Keep decision:

Keep. The package gained publish-critical assets without changing the core workflow contract or adding risky runtime dependencies.

## Publish Blockers

None for a private/shareable release candidate. The repository should remain private until the user explicitly asks to make it public.

Blocked actions without explicit user authorization:

- Make the GitHub repository public.
- Create a release tag.
- Publish to any public skill registry.
- Announce externally.

## Next Loop

Run Partner on one more frontend/UI task and require the complete phase:

```text
Claude plan -> Codex implementation -> Claude UI polish -> Codex fixes -> Claude review -> Codex verification
```

Then decide whether to make the repository public and tag `v0.1.0`.
