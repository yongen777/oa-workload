---
name: oa-workload
description: 把日常开发工作整理成可直接填报 OA 工时的交付物台账。当用户说「记工时 / 填 OA / 周五提交 / 这个月交付物够不够 / 出周提交单 / 补录交付物 / 这个任务算不算项目产出 / 这些是 teleagent 或 AI Studio 跑的结果」时使用。按 项目/月/周/日 四级落档；**每日件数严格按当天真实工作量统计，无下限、无上限、不套区间**；多来源（本 agent / teleagent / AI Studio / 手工）一并计入。绝不虚构交付物、绝不登记白名单外的材料。
agent_created: true
---

# OA 工时台账（oa-workload）

一套**纯本地、零依赖**的工时交付物台账：把每天真实做的工作沉淀成可填报的条目，周五一次性产出对照文本。

## ⭐ 计数口径（最高优先级）

**唯一依据 = 当天真实做了什么。**

- 没有日下限，没有日上限，没有「每天 2~3 件」这种区间目标；
- 不为了凑月度数量而给某天补件，也不为了「看起来均匀」而把真实产出压缩或摊平；
- 当天只干成一件事就记 1 件；当天产出十件就记 10 件；
- 月度参考线（默认 30 件/月）只用于提示，不参与生成、不驱动每日件数。

## ⭐ 来源覆盖（不得遗漏）

同一天的产出可能来自多个工具，**全部计入**：

| `--source` | 含义 |
|---|---|
| `workbuddy` | 本 agent 协助完成的产出（默认） |
| `teleagent` | 用户用 teleagent 跑出来的结果 |
| `ai_studio` | 用户用 AI Studio 等平台产出的结果 |
| `other_tool` | 其它工具 / 其它 agent |
| `manual` | 用户手工完成 |

用户把这些结果发过来时，登记前必须：① 逐条回显「事项 / 工时 / 交付内容 / 附件名」；② 回显条数并与用户给的条数对齐；③ 拿不准的工时或归类先问；④ 登记后把「当日工作量汇总（全部来源）」读回给他确认。

## 何时触发

| 用户说 | 执行 |
|---|---|
| 「记一下 / 今天做了这些」 | `log` 落当天 |
| 「这些是 teleagent / AI Studio 的结果」 | `log --source ...`，逐条计入 |
| 「新建项目 / 建工作区」 | `init` |
| 「这个月够不够 N 件」 | `audit`（只读核算，不阻断） |
| 「出提交单 / 周五了」 | `export-week`（report 模式不拦，只提示参考线） |
| 「桌面那些东西补登记」 | `harvest`（只出候选，不自动登记） |
| 「今天一共多少件」 | `status`（今日件数、来源分布、每日件数） |

**不触发**：与该项目无关的工作、个人项目、为维护本工具本身做的工作。

## 硬边界（任何情况都不得突破）

1. **不虚构交付物**。缺口只报缺口 + 给补齐路径，绝不生成凑数的假文件名。
2. **不猜系统枚举**。工作类型 / 事项清单 / 交付内容必须来自 `dictionaries.json`；`_verified: false` 时出单要打「未经系统核对」横幅。
3. **交付内容只认白名单**。不在 `soft_dev_whitelist`（或对应队伍白名单）里的值，`log` **直接拒绝登记**。
4. **不登记与项目无关的材料**。判断标准：**这条产出如果发给主管，他会不会认为是本项目的成果**。
5. **不自动提交**。只产出「可复制的填报文本 + 附件清单」，最终提交由用户手工确认。

## 命令

```bash
P="python $(dirname $0)/oa.py"

$P status                                        # 今日件数/工时、本周、本月、来源分布
$P init    --project <项目>
$P log     --project <项目> --type <工作类型> \
           --source workbuddy \
           --entry "事项|工时|做了什么" \
           --deliverable "交付内容|数量|文件名"
$P audit   --month 2026-10                       # report 模式恒 exit 0；strict 才 exit 1
$P export-week --project <项目> [--date YYYY-MM-DD] [--force]
$P rerender --project <项目>                     # 改附件名/格式后重渲染
$P harvest --from <目录> [--since YYYY-MM-DD]
```

`--entry` / `--deliverable` 可重复。数量 = 可独立审查的最小交付单元，一份文档算 1 件。
`quota.sanity` 默认 `0`（不限）；配置成 >0 时只做提示，不拒绝登记。

## 首次使用

```bash
cp config/settings.example.json     config/settings.json
cp config/projects.example.json     config/projects.json
cp config/dictionaries.example.json config/dictionaries.json
```

三个文件填完才能跑。`dictionaries.json` 必须从**你自己的 OA 表单**抄，不要按语义猜。

## 目录约定

```
<workspace>/<YYYY-MM>/<项目>/W_MMDD-MMDD/<YYYY-MM-DD>/
    ├── 当日填报.md      # 人读：清单类型 + 工时 + 交付物（含来源）+ 来源汇总
    └── 交付物/          # 附件
```

`<workspace>/_ledger/ledger.jsonl` 为唯一真源；设 `paths.ledger_in_project: true` 可把台账收进项目目录（注意：跨月统计会受影响）。

## 详细设计

见 `references/design-notes.md`：为什么按交付物计数、为什么用日期区间而不是周序号、数据模型、以及 2026-10-30 的口径变更（取消日配额闸门）。
