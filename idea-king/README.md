# 点子王 (Idea King)

从第一性原理出发 & 开启对抗式审查 — a first-principles decomposition +
adversarial review gate for plans, architectures, and work splits.
点子王是搭子.skill (Partner) Direction B 的派活前审查关卡，也可单独使用。

## Install 安装

Bundled with 搭子.skill — installing Partner installs idea-king:

```bash
bash install.sh          # from the partner-skill repo root
```

Standalone 单独安装（把本目录拷进 skills 目录即可）:

```bash
cp -r idea-king ~/.claude/skills/
```

## What it does 它做什么

- **Mode 1 第一性原理拆解** — strip analogies, list irreducible facts
  (physics / economics / convention), rebuild from zero, compare; then run
  Occam's razor as the twin check on anything no fact forces.
- **Mode 2 对抗式审查** — assume the plan WILL fail; find the 3 most
  probable causes of death, each with a falsification experiment designed
  under Murphy's law; work splits are priced with the Coase account.
- **Mode 3 盘问 (Grill)** — adversarial dialog: one question at a time,
  each shipping a recommended answer; anything answerable from the repo is
  looked up, never asked.

Fixed output: verdict / irreducible facts / attack points / survivors /
changes. 详见 [SKILL.md](SKILL.md) 与
[references/adversarial-checklist.md](references/adversarial-checklist.md)。

## Acknowledgments & Sources 致谢与来源

SKILL.md 刻意只录行为规则、不录原句——原句是咒语，效果随模型版本漂移；
行为规范跨模型稳定。原句和出处收在这里：

- 「从第一性原理出发 & 开启对抗式审查」— 社区流传的老提示语，本 skill 的
  起点；Mode 1 与 Mode 2 是它反编译后的行为版。
- 95% 信心追问原句（没有九成五的把握就先问澄清问题）与社区 "grill me"
  玩法 — Mode 3 盘问的两个祖先，规则里修掉了原句的已知 bug（置信度是
  修辞数字、一次一问不约束问什么）。
- 奥卡姆剃刀 — William of Ockham，如无必要勿增实体
  （[Occam's razor](https://en.wikipedia.org/wiki/Occam%27s_razor)）
  → Mode 1 step 5 孪生检查。
- 墨菲定律 — 凡是可能出错的，一定会出错
  （[Murphy's law](https://en.wikipedia.org/wiki/Murphy%27s_law)）
  → Mode 2 证伪实验设计与 happy-path 验收攻击。
- 科斯定理 — Ronald Coase,《企业的性质》(1937) /《社会成本问题》(1960)，
  交易成本决定边界
  （[Coase theorem](https://en.wikipedia.org/wiki/Coase_theorem)）
  → 工作拆分攻击与 Integration Cost 清单。
- 可证伪性 — Karl Popper
  （[Falsifiability](https://en.wikipedia.org/wiki/Falsifiability)）
  → 每个攻击点强制配一个最便宜的证伪实验。
- "DO NOT send optional commentary" — AGENTS.md 社区一行咒语；Rules 里的
  输出纪律是它的泛化版。
- Superpowers 6 autoresearch — 内部受控实验（diff-only 评审 5 份缺失任务
  书 0 命中）→ diff 盲验收攻击面。
