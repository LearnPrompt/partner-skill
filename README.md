<sub>🌐 <b>中文</b> · <a href="README.en.md">English</a></sub>

<div align="center">

# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-partner--skill-blueviolet)](SKILL.md)
[![GitHub stars](https://img.shields.io/github/stars/LearnPrompt/partner-skill?style=flat-square&color=f5c542)](https://github.com/LearnPrompt/partner-skill/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**把 Claude Code 留给规划、审美和审查，把 Codex 留给实现、跑检查和收尾。最后用一张 Session Receipt 证明：没有乱开新的 Claude 会话烧钱。**

[Showcase](#showcase) · [30 秒装上](#30-秒装上) · [一句话用起来](#一句话用起来) · [成本压力模型](#成本压力模型) · [它解决什么](#它解决什么) · [安全边界](#安全边界) · [验证](#验证)

</div>

---

## Showcase

Showcase 正在重做。上一版 GIF 没有把“Codex first pass 很平，Claude Code polish 后明显变好”讲清楚，所以先从公开 README 移除，避免误导第一次打开仓库的人。

新的 showcase 会只保留一个主线：**Codex 做出能跑但平的页面 -> 搭子把同一个 Claude Code 会话接回来做 UI polish / review -> 最后用 Session Receipt 证明没有乱开新 Claude 会话**。

在新图完成前，README 只保留协议、成本模型和可验证的小票，不把过程稿当成发布素材。

## 30 秒装上

最省事的方式，是直接把这个仓库链接发给你的 Agent：

```text
请安装搭子.skill：https://github.com/LearnPrompt/partner-skill
```

也可以用 `npx`：

```bash
npx skills add LearnPrompt/partner-skill -g
```

本地开发或手动安装：

```bash
git clone https://github.com/LearnPrompt/partner-skill.git
cd partner-skill
bash install.sh --target codex
bash install.sh --target claude
```

## 一句话用起来

```text
搭子，用同一个 Claude Code 会话先规划；我让 Codex 实现后，
你再把 diff 交回同会话做 UI polish 和 /codex:review，
最后给我 Partner Session Receipt，看有没有新开 claude -p。
```

更短一点：

```text
搭子，Claude 计划，Codex 实现，同会话 review，最后出 receipt。
```

## 成本压力模型

Partner 的省钱逻辑不是“少用 Claude”，而是**别让 Claude 反复冷启动**。最贵的浪费通常不是那一次 polish，而是 Codex 改完之后又开一个全新的 Claude review，让它重新读项目、重新理解目标、重新建立上下文。

当前 README 用的是 showcase workload model，不是 API billing telemetry。没有可靠 token 日志时，我们不编“省了多少 token”。这张表由 `scripts/showcase-cost-ledger.py` 生成，源数据在 `examples/showcase-cost-ledger.json`。

| 没有 Partner | 有 Partner |
|---|---|
| Claude 规划一次，Codex 改完后又新开 Claude review | 同一个 Claude Code 会话保留计划上下文 |
| 每次 review 都重新解释 repo、目标和 diff | Codex 只回传 bounded handoff |
| “省 token”说不清楚 | receipt 明确写 `new_claude_p_sessions: 0` |

三种模式可以这样看：

| 模式 | Codex 承担 | Claude Code 承担 | Claude 压力 | 适合场景 |
|---|---:|---:|---:|---|
| 纯 Codex | 100% 实现与检查 | 0% | 0.0x，但少了 Claude 的 UI / review 视角 | 低风险、无 UI 口味要求 |
| 搭子 Partner | 约 70% 实现、检查、修复 | 约 30% 计划、polish、review | 0.3x，并尽量避免重复 cold start | UI-heavy、功能多、需要省 Claude API 成本 |
| 纯 Claude Code | 0% | 100% 全流程 | 1.0x，机械改动也由 Claude 承担 | 很短任务，或用户明确要 Claude 全包 |

标准收尾小票：

```text
[Partner session receipt]
phase: final fix
claude_session: 9836fe7e-4aca-47a6-83b5-69086b8db275
claude_session_reused: yes
new_claude_p_sessions: 0
codex_passes: 2
checks: bash scripts/check-skill-repo.sh .; jq schema check; git diff --check
anomalies: none
```

没有可靠 telemetry 时，Partner 只报告能验证的事实：是否复用同一个 Claude 会话，是否新开 `claude -p`，检查是否通过，有没有异常。

## 它解决什么

你可能已经在 Codex 和 Claude Code 之间来回切了。真正麻烦的不是“它们能不能协作”，而是协作经常散掉：

- Claude Code 适合计划、UI 口味和 review，但让它包办所有机械改动很贵。
- Codex 适合长上下文实现、跑检查、修细节，但 UI polish 和最终审查需要另一个视角。
- 最浪费的是 Codex 实现完之后又新开 Claude，会话上下文全丢，Claude 重新读项目。
- 用户只听到“我用了 Claude”，但看不到到底有没有省钱。

Partner 把这件事变成固定协议：

```text
Claude Code same session:
  plan -> polish -> /codex:review

Codex:
  implement -> verify -> monitor -> fix -> receipt
```

## 触发方式

```text
搭子
搭子，帮我规划一下这个任务。
用 Claude Code goal 先规划，你 Codex 来实现。
同一个 Claude Code 对话里先出 plan，你实现后再让它 polish 和 /codex:review。
让 Claude skip 做完这个 UI 交互优化，你监控它。
Claude 里跑 Codex Review 验收当前 diff，发现问题你来修。
```

## 它会交付什么

- 清晰分工：Claude Code 负责计划、polish、review；Codex 负责实现、监控、验证、修复。
- 省预算默认策略：小中型任务尽量复用同一个 Claude Code 会话。
- Bounded handoff：只把 Claude 需要的计划、diff stat、检查结果和风险交回去。
- 监控清单：PTY、`claude agents --json`、transcript、task files、git diff/test 五层证据。
- Session Receipt：把是否复用会话、是否新开 `claude -p`、检查和异常写清楚。
- Darwin-style 验证门：一次只改一个协作维度，过检查才保留。

## 文件结构

```text
SKILL.md                         Runtime instructions for Codex/Claude-compatible agents
README.md                        中文入口
README.en.md                     English entrypoint
install.sh                       Local installer for Codex, Claude Code, Agents, or all targets
test-prompts.json                Trigger and behavior regression prompts
docs/showcase-cost-model.md      Showcase 成本压力模型与真实 token 记录字段
examples/session-receipt.md      Minimal visible proof of same-session reuse
examples/showcase-cost-ledger.json
                                  三种模式的成本压力 ledger
references/monitoring.md         How Codex monitors Claude Code progress
references/handoff-template.md   Bounded context packet for Claude Code polish/review
references/darwin-ratchet.md     Validation-gated improvement rules
scripts/showcase-cost-ledger.py  Rebuilds the showcase cost-pressure ledger
scripts/check-readme-parity.py   检查中英文 README 章节和关键证据是否对齐
scripts/check-skill-repo.sh      Publish readiness smoke check
```

## 安全边界

- `/goal` 只能在交互式 Claude Code 会话里用；不要用 `claude -p "/goal ..."`。
- `skip` / `bypassPermissions` 只在用户明确要求或隔离 worktree 里使用。
- skip 模式不等于允许 commit、push、deploy、publish、发外部消息或碰 secrets。
- 不默认新开 `claude -p` 做 final review；优先恢复同一个 Claude Code 会话。
- 不改 repo visibility、不打 tag、不发 registry、不公告，除非用户单独明确授权。
- 不用 `git reset --hard` 当默认回刀方案；优先用可审计 diff 或 revert。

## 验证

```bash
bash scripts/check-skill-repo.sh .
python3 scripts/check-readme-parity.py
jq -r '.[].id' test-prompts.json
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py
```

合格表现：

- `SKILL.md` 里有裸词 `搭子` 触发；
- `README.md` 和 `README.en.md` 的 11 个章节顺序完全对齐；
- README 不再展示未达标的 showcase 过程稿；
- `examples/showcase-cost-ledger.json` 能复现三种模式的成本压力表；
- `Partner Session Receipt` 在 `SKILL.md`、README 和测试 prompt 里都有；
- 本地检查 `fail=0`，只允许安全文档里的高风险命令 warning。

## License

MIT
