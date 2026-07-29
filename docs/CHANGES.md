# 与原版的完整差异记录

日期：2026-07-02

基线：上游 `LearnPrompt/partner-skill` @ `764f4bb`（fix: replace curly quotes with straight ASCII quotes in img tags）

本文档记录本地 fork 从原版到现在的全部改动：第一轮 bug 修复与风险加固（v1.1.0），第二轮六项能力进化（v1.2.0），第三轮"重度使用者审查"修复（v1.3.0）。所有改动都保持核心协议不变：Claude Code 负责 plan / polish / review，Codex 负责实现与验证，同会话复用，bounded handoff，以 Partner Session Receipt 收尾，不声称没有 telemetry 的 token 节省。

## Partner 2.0.1：Claude 规划链有界化

真实 Fable 5/xhigh 仓库规划证明“CLI 登录成功”和“复杂规划稳定交付”不是同一件事：模型成功读仓库并派生子 Agent，最终却在综合阶段 stream idle。v2.0.1 新增 `scripts/run-claude-plan.py`，由 Codex 先整理固定格式、最多 24,000 字符的事实包，再让配置中的 Claude identity 在 safe mode、零工具/子 Agent、wall/idle/API 预算内只做决策综合。

运行结果不靠一句 PASS：`.partner/runs/<run-id>/` 保留有大小上限的 sanitized events、visible checkpoint、metadata 和 recovery，同一 session 可恢复；配置缺失、身份字段变化后继承旧 verification、backend 不符、secret-like 内容、静默截断、并发覆盖既有计划和自动换模全部 fail closed。idle 只由完整有效的 JSON event 刷新，stdin/stdout/stderr、可见输出、日志和整个子进程组都有硬边界。即使 Claude CLI 返回 success，只要退出码非零、实际 model/session 不符、结果缺少固定八段 plan 契约或只输出一句过场话，也按 `protocol_error` 处理且不生成 plan。metadata 同时记录 packet/runner hash；`--max-budget-usd` 明确由 Claude CLI 执行，本地只记录最终可见成本，不虚构 mid-stream 累计成本。

## 一、Bug 修复与风险加固（v1.1.0）

### 1. README.md showcase 居中失效（bug 修复）

原版 `README.md` 第 23 行是 `<div align=”center”>`——curly quotes 导致 HTML 属性无效，中文版 showcase GIF 在 GitHub 上不居中。原版最后一个 commit 只修了 `<img>` 标签，漏了这个 `<div>`。已改回 ASCII 引号，并在 parity 检查里加了 curly-quote lint 防回归。

### 2. install.sh 重写（安全加固）

原版用 `rsync -a` 复制整个工作区（只排除 `.git` 和 `.DS_Store`），会把未跟踪的本地文件（测试日志、草稿、误放的敏感文件）一并装进 `~/.codex/skills/` 等三个目录，且备份目录无限累积、依赖 rsync。

现版本：

- 有 git 时用 `git ls-files` 只打包跟踪文件（额外排除 `.github/` 和 `docs/TEST.md`），无 git 时用 find + 显式排除；
- 复制改用 tar（macOS/Linux 通用），不再依赖 rsync；
- 旧安装的备份最多保留 3 份，超出自动清理；
- 每次安装写入 `.install-meta`（来源 commit + 安装时间），解决"装的是哪个版本"无从查证的问题。

### 3. SKILL.md skip 语义收紧（安全加固）

原版把用户说 "skip" 直接映射为启动 `--dangerously-skip-permissions`。现版本规定：只有当 skip 明确指权限模式时才升级权限；当 skip 可能指"跳过某个步骤"（如"跳过 polish"）时，必须先问一句确认。`test-prompts.json` 的 `explicit-skip-ui-polish` 用例同步更新。

### 4. check-skill-repo.sh 加固

- 扫描临时文件从写死的 `/tmp/partner-skill-*.txt` 改为 `mktemp` + trap 清理；
- secret 扫描从 3 种 pattern 扩到 7 种（新增 `ghp_`、`github_pat_`、AWS `AKIA`、Slack `xox`、更多私钥头）；
- 高危命令扫描不再对"禁止类"上下文（不要/Do not/禁止等）报永久 WARN；`test-prompts.json` 改由 jq 结构化校验——危险命令文字只允许出现在 `must_not` 数组；代码里的合法出现用 `risk-ok` 行内标注豁免；
- jq 缺失时 schema 检查不再静默跳过，改用 python3 兜底且失败算 FAIL;
- 固定字符串匹配统一改 `grep -F`，消除未转义 `.` 的弱匹配；
- 新增 SKILL.md 必须声明语义化 `version` 的检查。

### 5. 新增 GitHub Actions CI（原版无 CI）

`.github/workflows/checks.yml`：每次 push/PR 自动跑 smoke check、README parity、脚本语法、ledger 可复现性、安装 dry-run（v1.2.0 又追加了 receipt 校验、test-prompts 静态回归、监控探测冒烟）。

### 6. check-readme-parity.py 增强

- HTML 标签内出现 curly quotes 直接 FAIL（防第 1 条 bug 回归）；
- 锚点校验从"只比数量"升级为"每个锚点必须能解析到真实标题"（内置 GitHub 风格 slugify，支持中文标题）。

### 7. SKILL.md 增加 `version` frontmatter

原版无版本概念。现为 `version: 1.2.0`，检查脚本强制要求。

## 二、六轮能力进化（v1.2.0）

### 轮 1：CLI 能力探测与监控降级

新增 `scripts/check-claude-cli.sh`。监控五层信号中有三层依赖 Claude Code CLI 内部实现（`claude agents --json`、transcript 目录、task files），版本漂移会让监控静默失效。探测脚本在会话前运行，输出 `MONITORING_LEVEL=full|degraded|none`；SKILL.md 和 monitoring.md 要求把该等级写入 receipt，并且"探测说不可用的信号不得声称在用"。

### 轮 2：Receipt 机器可读化

- 新增 `docs/receipt-schema.json`（`partner.receipt.v1`）：receipt 的 JSON Schema；
- 新增 `scripts/validate-receipt.py`：解析文本 receipt 块或 JSON，校验必填字段、枚举取值、数值格式，并拒绝残留模板占位符；
- receipt 格式新增 `monitoring_level` 字段，同步更新了全部 7 处出现位置（SKILL.md、两份 README、monitoring.md、handoff-template.md、examples/session-receipt.md、showcase-cost-ledger.py 的字段清单与生成的 JSON）；
- `examples/session-receipt.md` 的示例 receipt 纳入 CI 校验。

### 轮 3：Handoff 工具化

新增 `scripts/make-handoff.sh`：自动收集 `git status --short`、`git diff --stat`、变更文件清单、可选检查命令的输出尾部，按 handoff 模板生成 markdown；判断类字段（plan 摘要、关键决策、tradeoffs）保留为显式 TODO。非 git 目录自动降级为 bounded file inventory。消除手工拼 handoff 时漏带证据的问题。

### 轮 4：失败手册与状态持久化

- 新增 `references/failure-playbook.md`：9 种异常（permission wait、idle 无 diff、idle 有 diff、空 review、review 卡死、会话崩溃、上下文过载、检查失败、监控降级）各给出"检测信号 → 恢复动作 → receipt 记法"的固定路径；
- 启用原版预留但未使用的 `.partner/` 目录：`plan.md` + `handoffs/`（由 `make-handoff.sh --save` 写入）+ `receipts/`。大任务/跨天任务丢会话后，用 `plan.md` + 最新 handoff 冷启动替代会话，不再从零重建上下文。

### 轮 5：场景矩阵

新增 `references/scenarios.md`，覆盖默认流程假设之外的六类场景：review-only（跳过 plan 阶段）、debugging/incident（Claude 出假设、Codex 复现验证的反向循环）、非 UI 任务（polish 重定义为 API 形状/报错/日志/文档）、非 git 目录（bounded inventory 替代 git 证据）、monorepo（git 命令限定 pathspec）、大型跨天任务（`.partner/` 持久化）。SKILL.md 默认流程第一步同步补了非 git 目标的降级说明，消除了与 monitoring.md 的不一致。

### 轮 6：test-prompts runner

新增 `scripts/run-test-prompts.py`：

- 静态模式（默认，进 CI）：校验 9 条回归用例的 id 唯一性、字段完整性、非空、危险命令文字仅限 `must_not`、receipt 契约用例存在；
- live 模式（实验性）：通过 `PARTNER_AGENT_CMD` 把每条 prompt 喂给真实 agent，检查输出含 receipt 块并调用 validate-receipt.py 校验。已用 stub agent 验证正反两条路径的判定和退出码。

尚未完成（需要真实工作流运行）：一次带 token telemetry 的 measured run。记录字段和 `--measured-json` 入口原版已备好，跑完真实数据即可把"workload model"升级为实测数据。

## 三、重度使用者审查修复（v1.3.0）

以"每天在用这个 skill 的人 + 有经验的 skill 创作者"双视角审查后，修复了两个潜在缺陷并补齐三组能力。

### 1. 脚本路径缺陷（真缺陷修复）

v1.2.0 的所有文档写的是 `bash scripts/...` 相对路径，但 Partner 运行时 cwd 是**目标 repo**，脚本装在 skill 安装目录里——真实使用场景下所有工具调用都会失败（只有在 skill 仓库自己身上测试才通过）。修复：SKILL.md 新增 "Tool Location" 一节定义 `$PARTNER_DIR`（skill 安装目录）约定，SKILL.md 与全部 references 里的脚本调用统一改为 `"$PARTNER_DIR/scripts/..."` 形式；确认全部脚本本身支持任意 cwd 运行（repo 相关的都有 `--repo` 参数）。

### 2. Receipt 模板一致性防线

receipt 模板块在 SKILL.md、monitoring.md、handoff-template.md 三处各有一份手工副本，字段变更靠人肉同步（v1.2.0 加 monitoring_level 时同步了 7 处，下次必漏）。修复：先统一了三处已存在的措辞差异（`codex_passes` 行），再在 `check-skill-repo.sh` 加入"receipt 模板一致性"检查——提取三个文件的模板块逐行 diff，漂移即 FAIL。已用故意损坏的副本做负向测试验证。

### 3. 证据从"自报"升级为"实证"

- 新增 `scripts/make-receipt.py`：从参数生成 receipt，自动运行探测填 `monitoring_level`，生成前先过校验器（非法输入拒绝输出，exit 1），`--save` 存入 `.partner/receipts/`。手打 receipt 的格式漂移和"凭印象填数"从源头消除。
- 新增 `scripts/session-snapshot.sh`：会话启动时快照 `~/.claude/projects/<munged-repo>/` 的 transcript 清单（每个会话包括 `claude -p` 都会留 transcript），receipt 时 diff 得出 `NEW_SESSIONS=<n>`——receipt 里最核心的 `new_claude_p_sessions` 从 agent 声称变为可计算的事实。命名规则经真实环境验证。

### 4. 恢复入口与触发词收紧

- 新触发语 `搭子，恢复`：从 `.partner/plan.md` + 最新 handoff 冷启动,机制在 v1.2.0 已建好，这次补上用户入口；SKILL.md、两份 README、failure-playbook 同步，`test-prompts.json` 新增第 10 条回归用例 `resume-from-partner-state`。
- 英文触发词从裸 "Partner" 收紧为 "Partner skill" / "Partner workflow"，并明确排除无关语境的 "partner" 一词，防误触发。

### 5. install.sh --status

对比三个安装目标的 `.install-meta` commit 与仓库 HEAD，输出 CURRENT / STALE / MISSING / UNKNOWN，解决多副本漂移无从察觉的问题。三种状态均实测。

### 6. 版本与 CI

SKILL.md 版本升至 1.3.0；CI 新增两个脚本的语法检查和 make-receipt → validate-receipt 的 roundtrip 冒烟。

尚未做（留待后续轮次）：receipt 聚合统计（receipt-stats）、每周 CI 装真实 CLI 做漂移检测、schema v1.x 字段演进政策（`additionalProperties: false` 下加字段是 breaking change，建议趁早决定是否补 `task`/`repo` 可选字段）、一次真实 measured run。

## 四、文件清单变化

新增文件（12 个）：

```text
.github/workflows/checks.yml     CI：全部检查自动化
docs/receipt-schema.json         Receipt JSON Schema (partner.receipt.v1)
docs/CHANGES.md                  本文档
references/failure-playbook.md   异常恢复手册 + .partner/ 布局
references/scenarios.md          六类场景的流程变体
scripts/check-claude-cli.sh      CLI 监控能力探测
scripts/make-handoff.sh          Bounded handoff 生成器
scripts/make-receipt.py          Receipt 生成器（生成前预校验，自动填 monitoring_level）
scripts/session-snapshot.sh      Transcript 快照对比（新会话数实证化）
scripts/validate-receipt.py      Receipt 校验器
scripts/run-test-prompts.py      回归 prompt runner（静态 + live）
docs/TEST.md                     首轮 clone/验证记录（本地，不随安装分发）
```

修改文件（12 个）：`SKILL.md`、`README.md`、`README.en.md`、`install.sh`、`test-prompts.json`、`examples/session-receipt.md`、`examples/showcase-cost-ledger.json`、`references/monitoring.md`、`references/handoff-template.md`、`references/failure-playbook.md`（v1.3.0 修订）、`references/scenarios.md`（v1.3.0 修订），以及三个 scripts（`check-skill-repo.sh`、`check-readme-parity.py`、`showcase-cost-ledger.py`）。

## 五、验证状态

以下全部实测通过（2026-07-02，v1.3.0 最终状态）：

```text
bash scripts/check-skill-repo.sh .          SUMMARY fail=0 warn=0（42 项 PASS，含 receipt 模板一致性）
python3 scripts/check-readme-parity.py      PASS（含锚点解析与 curly-quote lint）
python3 scripts/run-test-prompts.py         PASS static checks (10 cases)
python3 scripts/validate-receipt.py examples/session-receipt.md  PASS
scripts/check-claude-cli.sh                 三种环境实测：full / degraded / none 判定正确
scripts/make-handoff.sh                     git 仓库、非 git 目录、--check、--save、非法参数均按预期
scripts/make-receipt.py                     roundtrip 通过校验；非法输入 exit 1 拒绝输出；--save 落盘正确
scripts/session-snapshot.sh                 真实 transcript 目录实测：基线、零差异、缺基线 exit 3、新会话检测全对
receipt 模板一致性检查                        正向 PASS；故意漂移的副本被判 FAIL（负向测试）
run-test-prompts.py --live                  stub agent 正/反向用例判定与退出码正确
install.sh --status                         MISSING / CURRENT / STALE 三种状态实测正确
install.sh                                  假 HOME 实装：payload 干净、备份稳定在 3 份、.install-meta 正确
ledger 可复现                                SOURCE_DATE_EPOCH 固定后重复生成无 diff
bash -n / py_compile / git diff --check     全部通过
```
