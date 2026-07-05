# Red Skill 提交文案

## 简介

搭子.skill 是一套给 Claude Code 和 Codex 使用的双 Agent 协作协议。它不追求让某一个模型全包，而是把两边最值钱的能力拆开：Claude Code 负责规划、产品判断、UI polish 和最终 review；Codex 负责长上下文实现、改代码、跑检查、修复和收尾。这样做的核心不是口头说“省 token”，而是尽量复用同一个 Claude Code 会话，避免 Codex 做完以后又新开 Claude，让它重新读项目、重新理解目标、重新建立上下文。

这套 skill 适合中小型代码任务、前端体验打磨、复杂 diff review、多轮修复、跨天接续，以及“Claude 先想清楚，Codex 负责干活”的工作流。它会要求 Agent 先确认真实 repo 状态，再按固定流程产出 plan、bounded handoff、检查结果和 Partner Session Receipt。最终小票会写清楚：是否复用 Claude 会话、是否新开 `claude -p`、Codex 做了几轮、跑了哪些检查、有没有异常。它也支持反向工作流：Claude Code 主驾时，可以把机械、耗时、额度压力型任务分给 Codex 后台作业，Claude 再逐项验收。

一句话：搭子.skill 把“Claude 会想，Codex 会做”变成可复用、可验证、可恢复的协作流程。

## Skill介绍（压缩版）

# 搭子.skill (Partner)

> 我的 Claude Code 和 Codex 天下第一好。

搭子.skill 是一套面向 Claude Code 与 Codex 的双 Agent 协作协议。它的目标不是让某一个 Agent 从头包到尾，而是把两边最值钱的能力放在正确位置：Claude Code 做规划、审美、交互判断和最终审查；Codex 做实现、长上下文编辑、跑检查、修复和收尾。核心原则是：小中型任务尽量复用同一个 Claude Code 会话，让 Claude 保留原始目标、计划和审美上下文，避免 Codex 完成实现后又新开一个 Claude review，从零重读项目、重建上下文、重复烧成本。

## 什么时候使用

当用户说或暗示以下需求时使用：

- “搭子”
- “搭子.skill”
- “双向搭子”
- “Claude 计划，Codex 实现”
- “用 Claude Code goal 先规划，你来实现”
- “同一个 Claude Code 会话先出 plan，再 polish/review”
- “Claude 里跑 Codex Review”
- “让 Claude skip 做完”
- “分工给 codex”
- “codex 后台跑”
- “delegate to codex”
- “搭子，恢复”
- 想把 Claude Code 与 Codex 分工来节省 Claude API / 额度压力

不要因为普通英文 partner 一词触发；如果只是普通代码 review、没有 Claude Code 参与，也不必使用。

## 两个方向

搭子.skill 有两个方向，开始时先判断并说明：

Direction A：Codex 主驾。Codex 作为外层执行者和编排者，Claude Code 作为高价值 planning / polish / review Agent。这是默认路径。

Direction B：Claude Code 主驾。Claude Code 先规划、拆任务，把机械型、耗时型、额度压力型任务分给 Codex 后台作业，自己用 loop 监控进度，并在 Codex 交付后全量验收。

两种方向最终都要给 Partner Session Receipt，明确方向、会话复用、检查和异常。

## 默认流程：Codex 主驾

1. 进入真实项目目录  
不要停在总控目录或工作台根目录。先确认具体 repo，运行 `git status --short`。如果目标不是 git 项目，就记录有限文件清单。运行 `scripts/check-claude-cli.sh` 探测 Claude Code 可监控能力，并在最终小票里报告 `monitoring_level`。运行 `scripts/session-snapshot.sh start --repo <repo>`，让新开 Claude 会话数量可计算，而不是凭印象填写。

2. 启动同一个 Claude Code 会话做昂贵思考  
默认使用交互式 Claude Code，会话用于 plan、polish 和最终 review。规划阶段用 `claude --permission-mode plan --name <task-name>`，在会话内发送 `/goal <明确完成条件>`，让 Claude 输出实现计划、验收标准、UI/交互要求和风险。不要因为 Codex 做完实现就随手新开 `claude -p` 做 review。

3. Codex 负责主要实现  
Codex 把 Claude 的计划整理成短 checklist，按现有代码风格改文件、跑最快相关检查、修复失败项。机械改动、重复 lint、长命令循环、跨文件细节修正默认交给 Codex。

4. 把实现状态交回同一个 Claude Code 会话 polish  
特别是前端、交互、产品感、可访问性、边界状态。交回 Claude 的内容必须 bounded：原计划、改动文件、`git diff --stat`、关键检查结果、风险、待确认问题，以及必要文件片段。可以用 `scripts/make-handoff.sh` 生成 handoff 证据。要求 Claude 给优先级明确的问题，不要宽泛重写。

5. 同会话做最终 review  
在 Claude Code 里用 `/codex:review`。把发现的问题按 bug、风险、测试缺口优先处理，风格建议次之。Codex 修复阻塞项、重跑检查，最后输出 Partner Session Receipt。

## 反向流程：Claude Code 主驾

当用户希望 Claude Code 主驾、Codex 后台执行时，流程是：

1. Claude Code 写清目标、验收标准、约束和任务表。
2. 先过 idea-king 对抗式审查，确认任务拆分没有偷换目标、遗漏风险或把质量判断下放给错误 Agent。
3. Claude 用 `scripts/delegate-codex.sh` 提交 Codex 后台作业。
4. Claude 用 loop 监控 Codex job 状态、读取结果、必要时发起同 job 的 bounded fix round。
5. Claude 对 Codex 结果做全量 review，不能只信任务完成状态。
6. 收尾时写 Partner Session Receipt，记录 `direction: claude-driven` 和 `codex_jobs` 数量。

下沉执行优先级：搭子后台作业（走 Codex 订阅，可监控、可 resume）> 一次性 Codex subagent（卡住时补刀）> 更便宜的 Claude subagent（仍走 Claude API 计量）。质量关键判断留给 Claude。

## 会话策略

- 小中型任务：尽量复用一个 Claude Code 会话完成 `plan -> polish -> /codex:review`。
- 新开 Claude Code 会话视为昂贵操作；只有旧会话不可恢复、任务太大需要拆分，或用户明确要求时才开。
- 如果 Claude 会话卡在 permission、idle、无输出，先尝试继续或 resume 同会话。
- 大任务或巨大 diff：可以拆会话，但必须先由 Codex 生成紧凑 handoff。
- 跨天任务：把状态写到目标 repo 的 `.partner/`，包括 plan、handoffs、receipts。
- 用户说“搭子，恢复”时，优先读取 `.partner/plan.md` 和 `.partner/handoffs/` 里最新 handoff，不要从零重建上下文。
- UI / frontend 任务默认不要跳过 Claude polish，除非用户明确要求快速最小闭环。

## 权限边界

- 默认使用 `--permission-mode plan` 做规划。
- 只有用户明确说 skip、最高权限、全部允许、bypass，或任务在隔离 worktree 内，才使用 bypass/skip。
- skip 只是 Claude Code 权限升级，不代表可以 commit、push、deploy、publish、发外部消息或读取 secrets。
- 不默认改 repo visibility、不打 tag、不发 registry、不公告，除非用户单独明确授权。
- 不用 `git reset --hard` 作为默认回刀方案，优先用可审计 diff 或 revert。
- 不添加 analytics、telemetry、外部网络调用，除非用户要求。

## 分工规则

交给 Claude Code：

- 架构和实现计划
- UI / 交互 / 产品体验判断
- difficult product tradeoff
- 最终 Codex Review
- 高风险决策的第二视角

交给 Codex：

- repo 搜索和真实状态确认
- 代码实现和批量编辑
- 测试、构建、lint、脚本修复
- 长上下文文件整理
- 监控 Claude Code 状态
- 生成 handoff、receipt 和最终报告

如果功能技术通过但体验不行，必须回到 Claude Code 做 polish，而不是让 Codex 单独当最终审美裁判。

## Handoff 要求

交给 Claude 的内容要小而完整，不能把整个 repo 倒过去。推荐包含：

- 原目标和 Claude 的原计划
- 当前阶段
- 改动文件清单
- `git diff --stat`
- 已运行检查和结果
- 关键文件片段或必要全文
- 风险和未解决问题
- 需要 Claude 判断的具体问题

`scripts/make-handoff.sh` 可以自动收集 repo 证据，并可用 `--save` 写入 `.partner/handoffs/`。

## 监控与证据

不要只相信聊天文字，要尽量用五层信号：

1. 运行中的 Claude Code PTY 输出。
2. `claude agents --json --cwd <repo>` 的会话状态。
3. Claude JSONL transcript 结构，不默认泄露完整消息体。
4. `~/.claude/tasks/<sessionId>/` 下的任务文件。
5. repo 证据：`git status --short`、`git diff --stat`、测试/构建结果。

这些能力会随 Claude Code CLI 漂移，所以先用 `scripts/check-claude-cli.sh` 探测。最终小票里的 `monitoring_level` 只能写探测到的等级：`full`、`degraded`、`none` 或 `unknown`。

## Session Receipt

非平凡任务必须以 Partner Session Receipt 收尾。格式：

```text
[Partner session receipt]
phase: <planning | codex implementation | claude polish | review | final fix>
claude_session: <sessionId or none>
claude_session_reused: <yes | no | n/a>
new_claude_p_sessions: <0 | count | unknown>
codex_passes: <number>
checks: <commands run or not run>
anomalies: <none | permission wait | idle | empty review | failed check | other>
monitoring_level: <full | degraded | none | unknown>
direction: <codex-driven | claude-driven>
codex_jobs: <0 | count>
```

推荐用 `scripts/make-receipt.py` 生成，它会预校验字段并自动填监控等级。`new_claude_p_sessions` 应从 `scripts/session-snapshot.sh diff` 得到，不要凭感觉写。生成后可用 `scripts/validate-receipt.py` 对照 `docs/receipt-schema.json` 检查。

没有可靠 telemetry 时，不要编造 token 节省百分比。只报告可验证事实：是否复用同一 Claude Code 会话、是否新开 `claude -p`、是否使用 bounded handoff、检查是否通过、有没有异常。

## 恢复机制

`.partner/` 是跨天和断线恢复目录，通常包含：

```text
.partner/
  plan.md
  handoffs/
  receipts/
  jobs/
```

恢复规则：

- 先读 `.partner/plan.md`。
- 再读 `.partner/handoffs/` 最新 handoff。
- 如果是 Claude 主驾委派 Codex，读 `.partner/jobs/<jobId>/`。
- 用最新状态继续，不要重新设计整套方案。
- 如果状态缺失，向用户说明缺口，并从 repo 证据重建最小上下文。

## 改进原则

改进 workflow 时使用 Darwin-style ratchet：

- 一次只改一个维度：规划、实现、UI polish、review、监控、权限或报告。
- 先跑 test prompts 或真实 miniloop，再说改进有效。
- 高风险改动不能让同一个 Agent 同时当唯一作者和唯一裁判。
- 只有 repo 证据变好才保留改动。
- 如果继续 prompt 只能带来低信号，就停止。

## 配套文件

- `SKILL.md`：运行时主协议。
- `README.md`：中文入口。
- `README.en.md`：英文入口。
- `install.sh`：安装到 Codex、Claude Code、Agents 或全部目标。
- `test-prompts.json`：触发和行为回归 prompt。
- `docs/receipt-schema.json`：Session Receipt schema。
- `examples/session-receipt.md`：同会话复用示例。
- `references/monitoring.md`：Claude Code 监控方式。
- `references/handoff-template.md`：bounded handoff 模板。
- `references/failure-playbook.md`：异常恢复路径。
- `references/scenarios.md`：review-only、debugging、非 UI、非 git、monorepo、跨天任务变体。
- `references/claude-driven.md`：Claude 主驾委派 Codex 的五阶段流程。
- `references/goal-template.md`：`.partner/goal.md` 模板。
- `references/fable5-principles.md`：前沿模型提示词共同准则。
- `references/memory-protocol.md`：收尾记忆协议。
- `scripts/check-skill-repo.sh`：发布前 smoke check。
- `scripts/check-claude-cli.sh`：探测监控能力。
- `scripts/make-handoff.sh`：生成 handoff。
- `scripts/make-receipt.py`：生成 receipt。
- `scripts/session-snapshot.sh`：计算新会话数。
- `scripts/validate-receipt.py`：校验 receipt。
- `scripts/delegate-codex.sh`：Codex 后台任务 submit / status / result / resume / cancel。
- `idea-king/SKILL.md`：点子王，对方案做第一性原理拆解和对抗式审查。

## 验证命令

```bash
bash scripts/check-skill-repo.sh .
python3 scripts/check-readme-parity.py
jq -r '.[].id' test-prompts.json
SOURCE_DATE_EPOCH=1782921600 python3 scripts/showcase-cost-ledger.py
```

## 最终承诺

搭子.skill 不承诺神奇省钱，也不承诺某个 Agent 永远正确。它承诺的是流程可见、上下文尽量复用、分工可解释、异常可恢复、检查可复跑、结果可验收。让 Claude Code 把钱花在“想清楚”和“审得准”上，让 Codex 把力气花在“做出来”和“跑通过”上。最后用 receipt 把整个协作过程摊开给用户看。
