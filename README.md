<sub>🌐 <b>中文</b> · <a href="README.en.md">English</a></sub>

<div align="center">

# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-partner--skill-blueviolet)](SKILL.md)
[![Version: 2.0.1](https://img.shields.io/badge/version-2.0.1-ef6f4f)](CHANGELOG.md)
[![GitHub stars](https://img.shields.io/github/stars/LearnPrompt/partner-skill?style=flat-square&color=f5c542)](https://github.com/LearnPrompt/partner-skill/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**把 Claude Code 留给规划、审美和审查，把 Codex 留给实现、跑检查和收尾。v2.0.1 再把仓库级 Fable 规划变成有边界、可恢复、可审计的流程。**

[30 秒装上](#30-秒装上) · [Showcase](#showcase) · [一句话用起来](#一句话用起来) · [分宿主用法](#分宿主用法) · [成本压力模型](#成本压力模型) · [它解决什么](#它解决什么) · [安全边界](#安全边界) · [验证](#验证)

</div>

---

## 30 秒装上

一行 `npx` 装好：

```bash
npx skills add LearnPrompt/partner-skill -g
```

也可以直接把这个仓库链接发给你的 Agent：

```text
请安装搭子.skill：https://github.com/LearnPrompt/partner-skill
```

本地开发或手动安装：

```bash
git clone https://github.com/LearnPrompt/partner-skill.git
cd partner-skill
bash install.sh --target codex
bash install.sh --target claude
```

装完第一次用之前，说一句「搭子，配置」：搭子会打开只监听 `127.0.0.1` 的本地单页 UI。均衡/质量/成本三个起点和三个身份的具体 CLI/模型/effort 都在一页完成；页面先展示精确 diff，确认后才落盘。小白流程固定使用当前项目、本机 Git 忽略、安装后自动检查等安全默认值，不再追问高级选项。Codex 模型和每个模型支持的 effort 来自本机 CLI `model/list`，Claude 别名与 effort 来自 `claude --help`，绝不瞎猜。

<div align="center">
<p><strong>配置演示：切换工作模式、CLI、模型和推理强度</strong></p>
<a href="assets/config-switch-demo.mp4">
<img src="assets/config-switch-demo.gif" alt="Partner 配置页面演示：切换工作模式与三个搭子角色的 CLI、模型和推理强度" width="720" />
</a>
<p><a href="assets/config-switch-demo.mp4">打开 7 秒完整 MP4</a></p>
</div>

## Showcase

**Showcase 1：同会话 UI polish**

<div align="center">
<img src="assets/showcase.gif" alt="Codex-only vs Partner: before/after UI contrast" width="720" />
</div>

左边是 Codex 单独做出来的——功能正确但视觉上没什么记忆点。右边是同一个 Claude Code 会话接回来做 UI polish 后的结果，右下角 `session: reused ✓` 说明没有新开 Claude 会话。

**Showcase 2：真实 Fable 失败与恢复**

<div align="center">
<a href="assets/v2.0.1-conversation-cost-receipt.png">
<img src="assets/v2.0.1-conversation-cost-receipt.png" alt="Partner v2.0.1 对话消耗网页截图：角色运行映射、可核验成本、任务、推理强度和交付结果" width="720" />
</a>
<p><sub>真实网页截图：切换角色查看实际模型、effort、任务、成本与交付证据。</sub></p>
</div>

这不是一张“全部成功”的表，而是一条真实故障链。v2.0.1 的承诺不是 Fable 永不失败，而是失败不会无限跑、不会静默换模，也不会把半截结果当计划。

| 实际阶段 | 观测结果 | Claude CLI 返回成本 | Partner 怎么处理 |
|---|---|---:|---|
| v2.0.0 仓库规划 | 登录成功，派生 3 个子 Agent 后 stream idle；花费已发生但没有计划 | `$6.57` | 暴露旧流程无边界 |
| v2.0.1 fresh bounded attempt | 180 秒没有有效事件，`idle_timeout`；没有生成 plan | `unknown`（CLI 未返回最终成本） | 杀掉整个进程组，保留 metadata/checkpoint/recovery |
| 同 session resume | exact `claude-fable-5` / `xhigh`，返回有效八段计划 | `$0.382695` | 证明失败链可恢复，没有换模型 |
| 最终 fresh candidate | exact model/session、return code 0、packet/runner hash 一致 | `$0.45282` | 作为最终 Judge 与 PR 证据 |

这里的美元数是 Claude CLI 在对应真实 planning run 中返回的成本，不是整套工作流的 token 节省率；失败尝试没有 final result 时就诚实写 `unknown`。每个身份实际执行的任务、模型、effort 和逐次成本分别见 [v2.0.0 失败基线小票](examples/v2.0.0-conversation-cost-receipt.md)和 [v2.0.1 完整对话消耗小票](examples/v2.0.1-conversation-cost-receipt.md)。运行边界见 [`docs/releases/v2.0.1.md`](docs/releases/v2.0.1.md)、[`references/bounded-planning.md`](references/bounded-planning.md) 和 [`docs/showcase-cost-model.md`](docs/showcase-cost-model.md)。

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

第一次用先配置：

```text
搭子，配置
```

也可以从仓库直接打开：

```bash
bash install.sh --configure --host codex --repo /path/to/project
```

## 分宿主用法

**装在 Codex 里（Direction A，Codex 主驾）**

```bash
bash install.sh --target codex
```

```text
搭子
```

Codex 读到这份 SKILL.md 就自认宿主是 codex，走 `references/codex-driven.md`：自己编排实现、跑检查、修细节；Claude Code 只负责规划、UI polish 和最终 `/codex:review`，同一个 Claude 会话复用，不重复冷启动。

**装在 Claude Code 里（Direction B，Claude 主驾）**

```bash
bash install.sh --target claude
```

```text
搭子，分工给 codex 后台跑，做完你全量验收。
```

Claude Code 读到这份 SKILL.md 就自认宿主是 claude_code，走 `references/claude-driven.md`：规划、拆分、先过点子王对抗式审查，再把机械/额度压力型任务丢给 `delegate-codex.sh` 后台作业，用 loop 盯进度，最后全量 review 才接受。

宿主身份看的是"谁加载了这份 SKILL.md"，不是提示词里提到谁——在 Claude Code 里说"让 codex 做"不会让它把自己当成 Codex，反过来也一样。两边角色的模型/推理强度共用一份 `.partner/config.toml`，向导（见上）里选一次就够了。

## 成本压力模型

Partner 的省钱逻辑不是“少用 Claude”，而是**别让 Claude 反复冷启动**。最贵的浪费通常不是那一次 polish，而是 Codex 改完之后又开一个全新的 Claude review，让它重新读项目、重新理解目标、重新建立上下文。

当前 README 用的是 showcase workload model，不是 API billing telemetry。没有可靠数据支撑时，我们不声称能省多少 token。这张表由 `scripts/showcase-cost-ledger.py` 生成，源数据在 `examples/showcase-cost-ledger.json`。

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
monitoring_level: full
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

v1.4 起是双向搭子：反过来 Claude Code 主驾时，把机械、额度压力型任务分工给 Codex 后台跑，Claude 用 loop 盯进度、逐个全量验收，分工方案先过点子王（idea-king）的对抗式审查：

```text
Claude Code (driver):
  plan -> split (idea-king gate) -> delegate -> monitor loop -> full review -> receipt

Codex (background jobs):
  implement -> report -> bounded fix rounds on the same session
```

下沉执行有三条通道，按「电表落在订阅上」优先排序：搭子后台作业（`delegate-codex.sh`，走 Codex 订阅，可 loop 监控 + resume 返工）> 一次性 Codex subagent（卡住时补刀）> 更便宜的 Claude subagent（仍走 Claude API 计量，不省额度）。质量关键步即使贵也留 Claude。

<div align="center">
<img src="assets/showcase-idea-king.gif" alt="点子王对抗式审查:verdict 先行、攻击点带 evidence/inference 标签、证伪实验" width="720" />
</div>

分工方案先过点子王：结论先行（ship / needs-attention / no-go），每条攻击标注 evidence 或 inference，并附上最便宜的证伪实验。

宿主自识别，不靠猜：这份 SKILL.md 被谁加载（Claude Code 还是 Codex）就是谁的身份，提示词里提另一个 Agent 不会切换身份。角色的模型/推理强度只有一份事实源——`.partner/config.toml`（项目或全局），不会散落进 prompt 或文档里到处抄。

## 触发方式

```text
搭子
搭子，帮我规划一下这个任务。
用 Claude Code goal 先规划，你 Codex 来实现。
同一个 Claude Code 对话里先出 plan，你实现后再让它 polish 和 /codex:review。
让 Claude skip 做完这个 UI 交互优化，你监控它。
Claude 里跑 Codex Review 验收当前 diff，发现问题你来修。
搭子，恢复上次任务，接着做。
搭子，分工给 codex 后台跑，做完你全量验收。
搭子，配置
搭子，试跑
搭子，走完整协议，给我一个 PR 交付。
这个结论有争议，找仲裁者盲解一遍再定。
点子王，对抗式审查一下这个方案。
点子王，盘问我这个方案，一次问一个。
```

## 它会交付什么

- 清晰分工：Claude Code 负责计划、polish、review；Codex 负责实现、监控、验证、修复。
- 省预算默认策略：小中型任务尽量复用同一个 Claude Code 会话。
- Bounded handoff：只把 Claude 需要的计划、diff stat、检查结果和风险交回去。
- 监控清单：PTY、`claude agents --json`、transcript、task files、git diff/test 五层证据，配 `scripts/check-claude-cli.sh` 能力探测和降级策略。
- Session Receipt：把是否复用会话、是否新开 `claude -p`、检查、异常和监控等级写清楚，可用 `scripts/validate-receipt.py` 机器校验。
- 配套工具：`scripts/make-handoff.sh` 自动生成 bounded handoff 并可持久化到 `.partner/`；`references/failure-playbook.md` 给每种异常固定恢复路径；`references/scenarios.md` 覆盖 review-only、debugging、非 UI、非 git、monorepo、跨天任务。
- Bounded Claude planning：Codex 先整理 24,000 字符内的证据包，`scripts/run-claude-plan.py` 再按配置中的 Claude 模型/effort 做一次无工具、无子 Agent、有 wall/idle/API 预算的规划；成功与失败都留下可核验工件，绝不静默换模。
- Darwin-style 验证门：一次只改一个协作维度，过检查才保留。
- 首次配置向导（`搭子，配置`）：均衡/质量/成本预设可继续逐角色调整，`.partner/config.toml` 是双宿主共享的单一事实源；小白流程使用安全默认值，预览 diff 再落盘，绝不覆盖已有 agent 文件；模型和 effort 从两个 CLI 的真实能力列表读取，安装后自动启动无工具的新 Claude session 和 Codex dry-run 做验证。
- Partner Session Receipt v2：新增 `host`/`scope`/`config_source`/`roles_used` 字段，能证明这次跑的到底是哪个模型、哪个 effort，而不只是"用了 Claude"。
- 可选的完整协议（`references/goal-to-pr.md`）：Plan→Goal→PR→Verification，一路跑到 merge-ready + preview verified 为止；merge、上生产、打 tag、force-push、删除、破坏性迁移、对外发布，每一个都要单独一句祈使句授权。

## 文件结构

```text
SKILL.md                         Runtime instructions for Codex/Claude-compatible agents
README.md                        中文入口
README.en.md                     English entrypoint
install.sh                       Local installer for Codex, Claude Code, Agents, or all targets
test-prompts.json                Trigger and behavior regression prompts
docs/showcase-cost-model.md      Showcase 成本压力模型与真实 token 记录字段
docs/receipt-schema.json         Partner Session Receipt 的 JSON schema (partner.receipt.v1)
docs/config-schema.md            Partner 配置 schema v2：身份矩阵、优先级链、并发语义、TOML 子集边界
examples/session-receipt.md      Minimal visible proof of same-session reuse
examples/v2.0.0-conversation-cost-receipt.md
                                  2.0.0 失败基线的身份、模型、effort 与成本小票
examples/v2.0.1-conversation-cost-receipt.md
                                  本轮三个身份的真实任务、模型、effort 与成本小票
examples/showcase-cost-ledger.json
                                  三种模式的成本压力 ledger
references/monitoring.md         How Codex monitors Claude Code progress
references/handoff-template.md   Bounded context packet for Claude Code polish/review
references/failure-playbook.md   每种异常的固定恢复路径与 .partner/ 状态持久化
references/scenarios.md          Review-only、debugging、非 UI、非 git、monorepo、跨天任务的流程变体
references/darwin-ratchet.md     Validation-gated improvement rules
references/codex-driven.md       Direction A：Codex 主驾流程（Default Flow / Session Strategy / Permission Policy）
references/claude-driven.md      Direction B：Claude 主驾的五阶段委派流程
references/setup.md              「搭子，配置」首次配置向导：身份矩阵（三身份跨家搭配）+ 第二宿主增量接入
references/tryout.md             「搭子，试跑」身份试跑：三身份各跑一个微任务，出对照报告证明模型真生效
references/goal-to-pr.md         完整协议(可选)：Plan→Goal→PR→Verification、hard stop 清单、祈使句授权法
references/goal-template.md      .partner/goal.md 目标文件模板（任务表 + checkpoint 规则）
references/fable5-principles.md  前沿模型提示词共同准则（why-forward、effort、checkpoint、resume）
references/bounded-planning.md   仓库级 Claude 规划的输入契约、无工具执行边界、预算与恢复规则
references/memory-protocol.md    收尾记忆协议（claude-mem / mem0 / auto-memory / rollout）
scripts/showcase-cost-ledger.py  Rebuilds the showcase cost-pressure ledger
scripts/check-readme-parity.py   检查中英文 README 章节和关键证据是否对齐
scripts/check-skill-repo.sh      Publish readiness smoke check
scripts/check-claude-cli.sh      探测 Claude Code CLI 监控能力，输出 MONITORING_LEVEL
scripts/make-handoff.sh          自动收集 repo 证据生成 bounded handoff，可存入 .partner/
scripts/make-receipt.py          生成并预校验 receipt，自动填 monitoring_level，可存入 .partner/
scripts/session-snapshot.sh      transcript 快照对比，让新开会话数成为可计算的事实
scripts/validate-receipt.py      校验 Partner Session Receipt 的字段与取值
scripts/run-test-prompts.py      行为回归 prompt 的静态检查与实验性 live 模式
scripts/run-claude-plan.py       按配置运行 bounded Claude planner，保存 sanitized events/checkpoint/cost
scripts/delegate-codex.sh        Codex 后台任务原语：submit / status / result / resume / cancel
scripts/partner-config.py        配置引擎：TOML 子集解析、确定性写回、锁与原子写（schema v2）
scripts/partner_runtime.py       Claude 子进程共享环境边界，避免宿主变量污染一方 OAuth
scripts/partner-setup.py         向导落盘引擎：--preview/--apply/--rollback/--smoke/--status/--interactive
scripts/partner-setup-ui.py      localhost 单页配置 UI：完整模型矩阵、精确预览、确认写入
scripts/goal-sync.py             .partner/goal.md 哈希校验读写：并发写入不静默丢更新，冲突即 abort
tests/test_partner_config.py     配置引擎单元测试（round-trip / 锁 / 优先级链）
tests/test_partner_setup.py      向导引擎单元测试（幂等 / 防覆盖 / managed block / 回滚）
tests/test_partner_setup_ui.py   本地 UI 状态、预览绑定与写入门单元测试
tests/test_delegate_role.py      --role 注入与覆盖链单元测试
tests/test_goal_sync.py          goal.md 并发写入单元测试（哈希不符即拒绝，证明无静默丢更新）
tests/test_run_claude_plan.py    bounded planner 的输入、配置、预算、timeout、无 fallback 单元测试
idea-king/SKILL.md               点子王：第一性原理拆解 + 对抗式审查（随 Partner 一起安装）
idea-king/README.md              点子王独立说明与方法论致谢
```

## 安全边界

- `/goal` 只能在交互式 Claude Code 会话里用；不要用 `claude -p "/goal ..."`。
- `skip` / `bypassPermissions` 只在用户明确要求或隔离 worktree 里使用。
- skip 模式不等于允许 commit、push、deploy、publish、发外部消息或碰 secrets。
- 不默认新开 `claude -p` 做 final review；优先恢复同一个 Claude Code 会话。
- 不改 repo visibility、不打 tag、不发 registry、不公告，除非用户单独明确授权。
- 不用 `git reset --hard` 当默认回刀方案；优先用可审计 diff 或 revert。
- `.partner/config.toml` 默认不进 git（写进 `.git/info/exclude`，不动你的 `.gitignore`）；Codex 侧模型名绝不臆造，探测不到就报错等你给。
- Managed routing block（写进 CLAUDE.md/AGENTS.md 的常驻路由段）默认关闭，标记损坏的五种情形一律拒绝并解释，绝不猜测修复。
- 走完整协议（Plan→Goal→PR→Verification）也一样：merge、上生产、打 tag、force-push、删除、破坏性迁移、对外发布，各自需要独立的一句祈使句，不会因为前面一句「继续」就顺带做掉。

## 验证

```bash
bash scripts/check-skill-repo.sh .
python3 scripts/check-readme-parity.py
python3 -m unittest discover tests
jq -r '.[].id' test-prompts.json
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py
```

以上检查也会在每次 push 和 pull request 时由 GitHub Actions 自动运行（`.github/workflows/checks.yml`）。

## License

MIT

---

<div align="center">

**更多好用 Skill · More Skills** → [learnprompt.pro/skills](https://learnprompt.pro/skills/)

[鲁班·Skill打磨](https://github.com/LearnPrompt/luban-skill) · [庖丁·博主蒸馏](https://github.com/LearnPrompt/paoding-skill) · [蔡伦·对话造纸](https://github.com/LearnPrompt/cailun-skill) · [阿福·LLM Todo](https://github.com/LearnPrompt/afu-llm-todo) · [愚公·Loop工程](https://github.com/LearnPrompt/loop-engineering) · [搭子·结对开发](https://github.com/LearnPrompt/partner-skill) · [AI雷达·零API资讯](https://github.com/LearnPrompt/ai-news-radar)

[淘金小镇·ClawHub日榜](https://github.com/LearnPrompt/skillrush-town) · [Irasutoya·正文配图](https://github.com/LearnPrompt/carl-irasutoya-illustrations) · [Humanize PPT·演讲系统](https://github.com/LearnPrompt/humanize-ppt) · [CC Harness·六件套](https://github.com/LearnPrompt/cc-harness-skills) · [微信读书教练](https://github.com/LearnPrompt/carl-weread) · [X Article发布](https://github.com/LearnPrompt/x-article-publisher-skill)

<sub>**[LearnPrompt](https://github.com/LearnPrompt) 出品** · 公众号「卡尔的AI沃茨」 · [X @aiwarts](https://x.com/aiwarts)</sub>

<sub>致谢：`references/goal-to-pr.md` 的 done_when / anti-Goodhart / 祈使句授权法词汇，参考了 [愚公·Loop工程](https://github.com/LearnPrompt/loop-engineering) 的 goal-forging.md 与 guardrails.md（只借词汇与不变量，不搬 YAML 格式与仪式）。</sub>

</div>
