# Changelog

## Unreleased — feat/v1.5-dual-host

- fix: align the model matrix rows and synchronize the matrix/settings header grid without removing the routing motion
- feat: rebuild the setup UI as a kinetic local Agent routing console with live role mapping, purposeful motion, responsive layout, and reduced-motion support
- feat: localhost single-page setup UI with a taste-skill guided decision rail, concrete model matrix, exact diff preview, preview-bound confirmation, and smoke test without repeated chat questions
- config: balanced preset fast_worker now uses the detected Codex model with high reasoning effort
- feat: identity matrix — three cross-vendor identities (deep_reasoner / fast_worker / arbiter), each with its own backend/model/effort; schema v2 with fail-closed v1 migration (`5a1f3d7`, `52ad950`, `da269ce`)
- feat: arbiter blind-solve protocol + 搭子，试跑 first-run tryout; goal.md task table drops owner in favor of identity (`f329daf`)
- feat: idea-king adds 分工 (Assignment) section to Partner work-split reviews (`18dd247`)
- fix: wire per-task role decision into the split flow; clarify owner vs role (`983457f`, `493d561`, superseded by the identity matrix)

- test: dual-host CI sandbox matrix — install order, idempotence, fail-closed (`6333e8c`)
- fix: redirect codex exec stdin from /dev/null to prevent hung background jobs (`0d673cc`)
- docs: README bilingual rewrite — setup wizard, host self-ID, receipt v2, opt-in full protocol (`54ce055`)
- feat: goal-sync.py hash-checked goal.md read/write, no silent lost update (`94349df`)
- test: test-prompts.json +4 goal-to-pr case incl. ordinary-pr-no-trigger negative (`d99b630`)
- feat: Plan→Goal→PR→Verification protocol, references/goal-to-pr.md (`f5b9232`)
- feat: extend Partner Session Receipt with host/scope/config_source/roles_used, schema v2 (`5246d45`)
- feat: activate Sub Agent three-level routing, partner-* > user agent > generic Task (`3d5e077`)
- test: test-prompts.json +9 case — 4 setup, 4 host-adapter, 1 idea-king (`c6020f5`)
- feat: partner-setup.py wizard engine + references/setup.md, "搭子，配置" first-run setup (`5e3744b`)
- feat: install.sh --configure forwards to the terminal setup wizard (`9e95036`)
- feat: idea-king absorbs Occam/Murphy/Coase laws, ported from installed copy (`51a6389`)
- feat: idea-king clarify-to-95% pre-verdict protocol, headless degrades to Open Questions (`d86ae57`)
- refactor: split SKILL.md into Partner Core + references/codex-driven.md with host detection (`4cc5ccd`)
- feat: partner-config.py TOML-subset config engine (schema v1) with tests and docs (`760d938`)
- feat: delegate-codex.sh --role injection from partner-config, with --dry-run and tests (`63b6807`)
- feat: install.sh writes host= marker into .install-meta (`d9eab44`)
- test: run-test-prompts.py supports should_trigger:false negative cases (`b21cbe3`)
- fix: remove deprecated --enable web_search_cached from delegate-codex.sh (`30999a2`)

## v1.4.2 (2026-07-05)

- feat: idea-king absorbs official adversarial-review, grilling, and packet hygiene (`a1ddbc9`)
- docs: add idea-king adversarial-review showcase GIF to both READMEs (`4ab807c`)
- docs: add Red Skill submission copy for 搭子.skill (`9ebc3e7`)

## v1.4.1 (2026-07-04)

- feat: execution-channel routing + evidence-backed prompting principles (`ab679e8`)
- fix: harden bidirectional delegation utilities (`f5539bb`)

## v1.4.0 (2026-07-03)

- feat: bidirectional Partner + idea-king + frontier prompting & memory protocol (`a9b5dde`)

## v1.3.0 (2026-07-02)

- Release partner skill v1.3.0 (`e7266e8`)
- feat: showcase redesign with green palette, GSAP animation, and GIF (`e67966c`)
- fix: replace curly quotes with straight ASCII quotes in img tags (`764f4bb`)

## Earlier (2026-06-24 – 2026-07-01)

- Showcase and release polish: reproducible cost ledger, README parity release gate, README language split (`ad19e6c`, `efed0d8`, `8ebb5cf`, `3418b60`, `a266e94`, `b984911`, `c35955b`, `2eac3c1`)
- Public readiness: Partner session receipt, same-session Claude strategy, release preparation (`258779f`, `f87a17e`, `0ae1d81`, `7fa24da`)
- Origin: initial Claude Codex relay skill, renamed to Partner (`1ba62e6`, `5979fab`)
