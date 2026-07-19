# Partner configuration schema v1

Partner uses one TOML configuration shape at project and global scope. Each
host owns only its own `hosts.<host>` namespace; a host writer preserves the
other host, top-level comments, `[routing]`, and unknown sections as raw bytes.

## Locations and precedence

Values resolve from highest to lowest priority:

1. Session override supplied by the current task.
2. `<repo>/.partner/config.toml`.
3. `${XDG_CONFIG_HOME:-$HOME/.config}/partner/config.toml`.
4. Built-in defaults.

Project and global files use the same schema. Higher layers merge by field, so
an override for one role field does not erase unrelated lower-layer fields.
Built-in defaults provide schema metadata and `always_on_host_rules = false`;
role model values are explicitly selected and written by setup rather than
duplicated in this engine.

## Fields

| Path | Type | Required | Meaning |
|---|---|---:|---|
| `schema_version` | integer | yes | Must be `1`. |
| `revision` | non-negative integer | yes, reserved | Reserved for later optimistic concurrency checks; MVP does not compare or increment it. |
| `hosts.claude_code.roles.deep_reasoner.model` | string | per configured role | Claude model name or alias. |
| `hosts.claude_code.roles.deep_reasoner.effort` | string | per configured role | Requested reasoning effort. |
| `hosts.claude_code.roles.fast_worker.model` | string | per configured role | Claude model name or alias. |
| `hosts.claude_code.roles.fast_worker.effort` | string | per configured role | Requested reasoning effort. |
| `hosts.codex.roles.deep_reasoner.model` | string | per configured role | Model passed to `codex exec -m`. |
| `hosts.codex.roles.deep_reasoner.effort` | string | per configured role | Value passed as `model_reasoning_effort`. |
| `hosts.codex.roles.fast_worker.model` | string | per configured role | Model passed to `codex exec -m`. |
| `hosts.codex.roles.fast_worker.effort` | string | per configured role | Value passed as `model_reasoning_effort`. |
| `hosts.<host>.roles.<role>.verified` | boolean | no | Whether a smoke test or real run verified the role. |
| `hosts.<host>.roles.<role>.verified_at` | string | no | Verification timestamp supplied by the caller. |
| `routing.always_on_host_rules` | boolean | no | Whether setup writes persistent host routing rules; default `false`. |

Every configured role requires non-empty `model` and `effort` strings. Model
and effort compatibility is checked by the host setup/smoke layer, not by this
syntax engine.

## Host ownership and deterministic writes

`--host claude_code` may rewrite only `[hosts.claude_code.roles.*]` sections;
`--host codex` may rewrite only `[hosts.codex.roles.*]`. The owned role sections
are emitted deterministically in schema order: `model`, `effort`, `verified`,
then `verified_at`. Strings are emitted as double-quoted strings. Repeating the
same write produces identical bytes.

Comments and formatting inside an owned section are intentionally not retained.
All unowned chunks remain in their original order and retain their original
bytes, including comments and line endings.

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

`revision` exists for a later defense-in-depth optimistic concurrency check. It
has no concurrency behavior in schema v1 MVP.

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
host's role sections. This boundary is what allows an unowned host section or
future unknown section to round-trip without reformatting.

## CLI

Run from the repository root:

```sh
python3 scripts/partner-config.py --host codex --scope project init
python3 scripts/partner-config.py --host codex --scope project validate
python3 scripts/partner-config.py --host codex --scope project get hosts.codex.roles.deep_reasoner.model
python3 scripts/partner-config.py --host codex --scope project set --role deep_reasoner --model MODEL --effort xhigh
python3 scripts/partner-config.py --host codex --repo /path/to/repo resolve
python3 scripts/partner-config.py --host codex --repo /path/to/repo resolve --override deep_reasoner.effort=high
```

Use `--scope global` to target the XDG/HOME location. `resolve` always evaluates
the complete precedence chain; `get`, `set`, `validate`, and `init` target the
selected scope.
