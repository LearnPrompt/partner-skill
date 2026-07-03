# Partner Skill 本地克隆、理解与测试记录

日期：2026-07-02

执行目录：`/Users/yichenlin/Desktop/Work`

目标仓库：`https://github.com/LearnPrompt/partner-skill`

本地目录：`/Users/yichenlin/Desktop/Work/partner-skill`

## 1. 本次任务目标

这次的任务是把 `LearnPrompt/partner-skill` 仓库完整 clone 到 Work 目录下，理解这个 folder 的用途，运行它能提供的本地测试和验证命令，并把本次执行过的动作、观察到的结果、测试结论完整写入 `docs/TEST.md`。

我没有把这个 skill 安装到用户的 `~/.codex`、`~/.claude` 或 `~/.agents` 目录里；安装相关命令只做了 `--dry-run`。我也没有 commit、push、tag、release 或发布任何东西。

## 2. Clone 结果

执行的 clone 命令：

```bash
git clone --recurse-submodules https://github.com/LearnPrompt/partner-skill.git partner-skill
```

clone 后确认信息：

```text
本地路径：/Users/yichenlin/Desktop/Work/partner-skill
当前分支：main
当前提交：764f4bbcb1953bf4e6a7fd935b3f7d73f27b9b40
远程地址：https://github.com/LearnPrompt/partner-skill.git
仓库大小：约 1.9M
可见文件数：16
子模块：无输出，说明当前没有需要初始化的 git submodule
最终 git status：干净，然后新增本文件 docs/TEST.md
```

最后一条提交信息：

```text
作者：HongjingLi <learnprompt2023@gmail.com>
时间：2026-07-02T02:36:24-07:00
标题：fix: replace curly quotes with straight ASCII quotes in img tags
```

## 3. 仓库整体用途

这个仓库不是一个传统应用，也不是一个需要启动服务的项目。它是一个 Agent Skill，名字叫 `partner-skill`，中文名是“搭子.skill”。它的核心用途是为 Codex 和 Claude Code 之间的协作建立一套固定协议：

- Claude Code 负责高价值判断：规划、UI/交互 polish、最终 review。
- Codex 负责主要落地：读仓库、实现代码、跑检查、修复问题、整理证据。
- 小中型任务默认复用同一个 Claude Code 会话，避免 Codex 实现后再新开一个 Claude review 会话导致上下文冷启动。
- 最终输出 Partner Session Receipt，记录是否复用 Claude 会话、是否新开 `claude -p`、Codex 修复轮次、检查命令和异常情况。

这个 skill 强调的是“可验证的协作流程”，不是声称真实节省了多少 token。仓库明确区分了两件事：

- 可以验证的事实：是否复用同一个 Claude Code session、有没有新开 `claude -p`、跑了哪些检查、有无异常。
- 只是模型的部分：README 里的成本压力比例是 workload model，不是 API billing telemetry。

## 4. 主要文件结构

我阅读和理解了这些关键文件：

```text
SKILL.md
README.md
README.en.md
install.sh
test-prompts.json
docs/showcase-cost-model.md
examples/session-receipt.md
examples/showcase-cost-ledger.json
references/monitoring.md
references/handoff-template.md
references/darwin-ratchet.md
scripts/check-skill-repo.sh
scripts/check-readme-parity.py
scripts/showcase-cost-ledger.py
assets/showcase.gif
LICENSE
```

各文件作用简述：

- `SKILL.md`：真正的 runtime skill 说明，包含触发词、默认流程、权限策略、Claude/Codex 分工、监控方式、输出契约和 Partner Session Receipt 格式。
- `README.md`：中文入口，解释安装、使用方式、成本压力模型、解决的问题、安全边界和验证命令。
- `README.en.md`：英文入口，和中文 README 保持同样的信息结构。
- `install.sh`：本地安装脚本，可把该 skill 安装到 Codex、Claude Code、Agents 或全部目标目录。
- `test-prompts.json`：行为回归 prompt 集合，用来描述哪些用户话术应该触发 Partner skill，以及每类 prompt 的预期行为和禁止行为。
- `docs/showcase-cost-model.md`：解释 showcase 成本压力模型，强调不要把 workload model 说成真实 token 节省。
- `examples/session-receipt.md`：Partner Session Receipt 示例。
- `examples/showcase-cost-ledger.json`：三种工作模式的成本压力 ledger。
- `references/monitoring.md`：Codex 如何监控 Claude Code session，包括 PTY、`claude agents --json`、transcript、task files、repo diff/test evidence。
- `references/handoff-template.md`：Codex 把已实现状态交回同一个 Claude Code 会话做 polish 或 review 时使用的 bounded handoff 模板。
- `references/darwin-ratchet.md`：改进这个 workflow 时的验证门，要求一次只改一个维度，经过测试才保留。
- `scripts/check-skill-repo.sh`：发布前 smoke check，检查必需文件、README 对齐、JSON schema、触发词、安全文本、secret scan 等。
- `scripts/check-readme-parity.py`：检查中英文 README 的章节、锚点和关键 marker 是否保持结构对齐。
- `scripts/showcase-cost-ledger.py`：生成 `examples/showcase-cost-ledger.json`，也可以输出 README 可用的 markdown 表格。
- `assets/showcase.gif`：README 展示图，检测结果是 GIF 89a，尺寸 720 x 448。

## 5. 我运行过的验证命令与结果

### 5.1 发布 readiness smoke check

命令：

```bash
bash scripts/check-skill-repo.sh .
```

结果：通过，`fail=0`。检查内容包括：

- 必需文件存在：`SKILL.md`、`README.md`、`README.en.md`、`test-prompts.json`、`install.sh`、`LICENSE`、示例和 docs 文件。
- 必需目录存在：`references`、`examples`、`scripts`。
- README parity gate 通过。
- `test-prompts.json` schema 通过。
- `SKILL.md` frontmatter 里的 name 是 `partner-skill`。
- `SKILL.md` 包含裸触发词 `"搭子"`。
- 中文 README 包含 Partner 身份和 slogan。
- 中英文 README 互相链接。
- README 链接了 `docs/showcase-cost-model.md`。
- showcase asset 存在并被 README 引用。
- showcase cost ledger 存在并被两个 README 引用。
- Partner Session Receipt contract 存在于 `SKILL.md`、`README.md` 和 `test-prompts.json`。
- secret scan 通过。

唯一 warning：

```text
WARN high-risk command text found
```

具体扫到的是 `git reset --hard` 等文字，但上下文都是安全边界，例如“不要默认使用 `git reset --hard`”。所以这是静态扫描的保守 warning，不代表仓库真的要执行危险命令。

### 5.2 README 中英结构对齐检查

命令：

```bash
python3 scripts/check-readme-parity.py
```

结果：

```text
PASS README parity
```

这个检查确认了中英文 README 的主要章节顺序一致，关键 marker 都存在，文件结构列表顺序也保持一致。

### 5.3 test-prompts.json 可解析与行为用例清单

命令：

```bash
jq -r '.[].id' test-prompts.json
```

结果列出了 9 个行为回归用例：

```text
session-receipt-required
bare-dazi-trigger
avoid-fresh-claude-review
plan-first-greenfield
same-session-plan-polish-review
explicit-skip-ui-polish
review-only-claude-codex-review
publish-readiness-check
bounded-handoff-template
```

这些用例覆盖了 Partner skill 的主要触发方式和行为边界，包括：

- 裸 `搭子` 触发。
- 同一个 Claude Code 会话完成 plan、polish、review。
- 避免默认新开 `claude -p` review。
- Claude Code 只做计划，Codex 做实现。
- UI polish 后再同会话 `/codex:review`。
- 用户明确说 skip 时才使用高权限 Claude Code session。
- review 结果由 Codex 修复并 rerun checks。
- 发布验收不自动 tag/release。
- 使用 bounded handoff template，而不是把整个仓库塞给 Claude。

### 5.4 成本压力 ledger 生成检查

命令：

```bash
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py --markdown
```

结果：脚本成功生成/刷新：

```text
/Users/yichenlin/Desktop/Work/partner-skill/examples/showcase-cost-ledger.json
```

并输出 markdown 表格：

```markdown
| Mode | Codex workload | Claude Code workload | Claude pressure | Measured tokens |
|---|---:|---:|---:|---|
| Codex-only | 100 | 0 | 0.0x | not captured |
| Partner | 70 | 30 | 0.3x | not captured |
| Pure Claude Code | 0 | 100 | 1.0x | not captured |
```

随后检查 `git diff -- examples/showcase-cost-ledger.json` 没有输出，说明在固定 `SOURCE_DATE_EPOCH` 后，生成结果与仓库当前文件一致。

### 5.5 安装脚本语法检查

命令：

```bash
bash -n install.sh
bash -n scripts/check-skill-repo.sh
```

结果：无输出，退出码为 0，表示 Bash 语法检查通过。

### 5.6 Python 脚本语法检查

命令：

```bash
python3 -m py_compile scripts/check-readme-parity.py scripts/showcase-cost-ledger.py
```

结果：无输出，退出码为 0，表示两个 Python 脚本都可以成功编译。

这一步生成了 `scripts/__pycache__` 临时缓存。我已在测试结束后删除该缓存目录，避免把测试副产物留在仓库里。

### 5.7 安装 dry-run 检查

命令：

```bash
bash install.sh --target codex --dry-run
bash install.sh --target all --dry-run
```

结果：脚本正确打印将安装到的目标路径，但因为使用了 `--dry-run`，没有实际写入这些目录。

dry-run 目标包括：

```text
/Users/yichenlin/.codex/skills/partner-skill
/Users/yichenlin/.claude/skills/partner-skill
/Users/yichenlin/.agents/skills/partner-skill
```

### 5.8 Git 空白检查

命令：

```bash
git diff --check
```

结果：无输出，退出码为 0。说明当时没有 whitespace error。

## 6. 重要行为和边界理解

这个 skill 的关键不是“让 Claude 和 Codex 都做点什么”，而是把两个 agent 的分工固定下来，减少上下文浪费，并让用户看到可验证证据。

它的默认流程是：

1. 先进入具体目标 repo，不在泛用 workbench 根目录里工作。
2. 运行 `git status --short`，确认当前仓库状态。
3. 对小中型任务启动一个 Claude Code session，默认用 plan 权限。
4. 在 Claude Code 交互会话里使用 `/goal`，拿到计划、验收标准、UI/交互建议。
5. Codex 负责主要实现和检查。
6. Codex 把 bounded handoff 发回同一个 Claude Code session 做 polish。
7. 同一个 Claude Code session 再跑 `/codex:review`。
8. Codex 修复 blocking findings，rerun checks。
9. 最后输出 Partner Session Receipt。

安全边界包括：

- 不把 `/goal` 通过 `claude -p` 发送；`/goal` 是交互式 Claude Code 命令。
- 不默认用 fresh `claude -p` 做最终 review。
- `skip` 或 `bypassPermissions` 只有在用户明确要求或隔离 worktree 时才使用。
- skip 不等于允许 commit、push、deploy、publish、发送外部消息或触碰 secrets。
- 不默认 `git reset --hard`，而是使用可审计 diff 或 revert。
- 没有 token telemetry 时，不声称真实 token savings。

## 7. 当前发现的问题或风险

没有发现会导致测试失败的问题。

需要注意的点：

- `scripts/check-skill-repo.sh` 会报告一个 high-risk command warning，因为它扫描到了文档里出现的 `git reset --hard` 字样。但这些文本是在禁止或约束危险命令，并不是实际执行命令。
- 当前成本节省说法是 workload model，不是实测 billing telemetry。文档已经明确说明这一点，后续对外介绍时应继续避免说“真实节省 70% token”之类没有 telemetry 的说法。
- 本次只是验证 skill 仓库本身，没有真的启动 Claude Code session 跑一次完整 Partner workflow；原因是当前任务是 clone、理解、静态/脚本验证和文档总结，不是要实际使用 Partner 协议完成某个业务开发任务。

## 8. 最终结论

`partner-skill` 已经完整 clone 到：

```text
/Users/yichenlin/Desktop/Work/partner-skill
```

我已阅读它的核心说明、脚本、测试 prompt、示例和参考文档。这个 folder 的作用是提供一个 Codex + Claude Code 协作 skill：Claude Code 负责规划、UI/交互 polish 和 review，Codex 负责实现、验证、修复和证据整理。它的亮点是复用同一个 Claude Code session，并通过 Partner Session Receipt 把“有没有冷启动新 Claude session”这类事实透明化。

本地验证结果整体通过：

```text
bash scripts/check-skill-repo.sh .                     PASS，fail=0，warn=1
python3 scripts/check-readme-parity.py                 PASS
jq -r '.[].id' test-prompts.json                       PASS
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py --markdown  PASS
bash -n install.sh                                     PASS
bash -n scripts/check-skill-repo.sh                    PASS
python3 -m py_compile scripts/check-readme-parity.py scripts/showcase-cost-ledger.py  PASS
bash install.sh --target codex --dry-run               PASS
bash install.sh --target all --dry-run                 PASS
git diff --check                                       PASS
```

结论：这个仓库作为一个可发布/可安装的 Agent Skill，本地 smoke check、README 对齐检查、JSON schema、成本 ledger 生成、安装 dry-run 和脚本语法检查都通过。除了一条预期内的保守 warning 外，没有发现阻塞性问题。
