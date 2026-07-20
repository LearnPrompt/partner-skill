# Partner configuration schema v2

Partner uses one TOML configuration shape at project and global scope. Each
host owns only its own `hosts.<host>` namespace; a host writer preserves the
other host, top-level comments, `[routing]`, and unknown sections as raw bytes.

An identity is the complete routing choice `backend + model + effort`. Tasks
select one of `deep_reasoner`, `fast_worker`, or `arbiter`; the identity's
`backend` determines which CLI executes it, independently of the driving host.

## Locations and precedence

Values resolve from highest to lowest priority:

1. Session override supplied by the current task.
2. `<repo>/.partner/config.toml`.
3. `${XDG_CONFIG_HOME:-$HOME/.config}/partner/config.toml`.
4. Built-in defaults.

Project and global files use the same schema. Higher layers merge by field, so
an override for one identity field does not erase unrelated lower-layer fields.
Built-in defaults provide schema metadata, empty identity maps, and
`always_on_host_rules = false`; model presets belong to setup and are not
duplicated in this engine.

## Example

```toml
schema_version = 2
revision = 0

[hosts.claude_code.identities.deep_reasoner]
backend = "claude"          # claude | codex — 哪家 CLI 执行
model = "opus"
effort = "high"
verified = false

[hosts.claude_code.identities.fast_worker]
backend = "codex"
model = "gpt-5.6-sol"
effort = "medium"
verified = false

[hosts.claude_code.identities.arbiter]
backend = "codex"
model = "gpt-5.6-sol"
effort = "xhigh"
verified = false

[routing]
always_on_host_rules = false
```

## Fields

| Path | Type | Required | Meaning |
|---|---|---:|---|
| `schema_version` | integer | yes | Must be `2`. |
| `revision` | non-negative integer | yes, reserved | Reserved for later optimistic concurrency checks; the current engine does not compare or increment it. |
| `hosts.<host>` | table | per configured host | `<host>` is `claude_code` or `codex`; each host owns its namespace. |
| `hosts.<host>.identities.<identity>` | table | per configured identity | `<identity>` is `deep_reasoner`, `fast_worker`, or `arbiter`. |
| `hosts.<host>.identities.<identity>.backend` | string enum | per configured identity | Required execution CLI: `claude` or `codex`. |
| `hosts.<host>.identities.<identity>.model` | string | per configured identity | Non-empty model name or alias passed to the selected backend. |
| `hosts.<host>.identities.<identity>.effort` | string | per configured identity | Non-empty reasoning effort passed to the selected backend. |
| `hosts.<host>.identities.<identity>.verified` | boolean | no | Whether a smoke test or real run verified the identity. |
| `hosts.<host>.identities.<identity>.verified_at` | string | no | Verification timestamp supplied by the caller. |
| `routing.always_on_host_rules` | boolean | no | Whether setup writes persistent host routing rules; default `false`. |

Every configured identity requires `backend`, `model`, and `effort`. Backend is
validated by this engine; model and effort compatibility is checked by the
setup/smoke layer.

## Host ownership and deterministic writes

`--host claude_code` may rewrite only
`[hosts.claude_code.identities.*]` sections; `--host codex` may rewrite only
`[hosts.codex.identities.*]`. The owned identity sections are emitted in
identity order (`deep_reasoner`, `fast_worker`, `arbiter`) and field order:
`backend`, `model`, `effort`, `verified`, then `verified_at`. Strings are
double-quoted. Repeating the same write produces identical bytes.

Comments and formatting inside an owned section are intentionally not retained.
All unowned chunks remain in their original order and retain their original
bytes, including comments and line endings.

## Schema v1 migration

Schema v1 is never converted silently. A file with `schema_version = 1`, or
with any `hosts.<host>.roles.*` section even if its version says otherwise,
fails closed in `resolve`, `get`, `set`, and `validate`. The error includes the
configuration path and this instruction:

> 检测到 schema v1 配置，请重跑 搭子，配置 升级（旧值会作为向导初值）

The setup wizard may call `read_legacy_v1(text, host)` to read only the old
`deep_reasoner` and `fast_worker` `model`/`effort` values as initial answers.
That path does not write or convert the source text. The wizard's eventual
save writes schema v2 identities through the normal locked, atomic writer.

## Concurrency and atomicity

A write creates `.config.lock` in the directory containing `config.toml` using
atomic `os.mkdir`. Its `info` file records `pid`, Unix `ts`, and `host` (plus an
internal ownership token). While holding the lock, the writer reads the latest
file, changes its host namespace, writes a same-directory temporary file, and
commits with `os.replace`.

- A lock whose PID is dead is reclaimed immediately.
- A live PID holding the lock for more than 15 seconds is treated as stuck and
  reclaimed.
- Otherwise the writer retries five times with exponential backoff (about 1.6
  seconds total), then fails closed and reports the owner and manual cleanup
  path.

`revision` remains reserved for a later defense-in-depth optimistic concurrency
check and has no concurrency behavior in schema v2.

## Supported TOML subset

The parser supports bare keys, double-quoted strings, integers, booleans,
standard table headers, basic single-line arrays, and `#` comments. It is not a
general TOML parser.

The following constructs fail closed with a line number, character position,
and a pointer back to this section:

- inline tables (`value = { ... }`);
- multiline strings;
- datetime values;
- array-of-tables headers (`[[...]]`);
- dotted-key assignments (`a.b = ...`).

The engine parses only top-level schema metadata, `[routing]`, and the selected
host's identity sections. This boundary allows an unowned host section or
future unknown section to round-trip without reformatting.

## CLI

Run from the repository root:

```sh
python3 scripts/partner-config.py --host codex --scope project init
python3 scripts/partner-config.py --host codex --scope project validate
python3 scripts/partner-config.py --host codex --scope project get hosts.codex.identities.deep_reasoner.backend
python3 scripts/partner-config.py --host codex --scope project set --role deep_reasoner --backend codex --model MODEL --effort xhigh
python3 scripts/partner-config.py --host codex --repo /path/to/repo resolve
python3 scripts/partner-config.py --host codex --repo /path/to/repo resolve --override deep_reasoner.effort=high
```

The `set` command retains `--role` as its identity selector. `--backend` is
required when creating an identity and may be omitted on update to preserve the
current value. `get` and `resolve` include `backend` in each configured identity.

Use `--scope global` to target the XDG/HOME location. `resolve` always evaluates
the complete precedence chain; `get`, `set`, `validate`, and `init` target the
selected scope.
