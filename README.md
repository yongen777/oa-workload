# oa-workload

把日常开发工作整理成**可直接填报进 OA 工时系统**的交付物台账 —— 按「项目 / 月 / 周 / 日」四级落档，**每日件数严格按当天真实工作量统计**，导出一份照着填的对照文本。

> 适用场景：公司要求每月提交 ≥N 个「研发过程文档类」交付物（需求记录、设计文档、功能模块代码、测试记录、部署手册……），但你真正的产出散在代码仓库、聊天记录、几个不同的 AI 工具里，月底才开始回忆。

---

## 它解决什么

| 痛点 | 做法 |
|---|---|
| 月底回忆这个月干了啥 | 每天一条 `log`，台账自动累积，随时可查 |
| 不知道这周够不够件数 | `audit` 当场算，只提示参考线，不逼你凑 |
| 产出散在多个工具里（本 agent / teleagent / AI Studio / 手工） | `--source` 标记来源，同日合并统计，一条都不漏 |
| 填报时对着空表单发呆 | `export-week` 产出逐日明细 + 交付内容 + 附件清单，照着抄 |
| 交付物名和系统下拉对不上 | 字典配置 + 白名单硬校验，填错根本不让你登记 |
| 为了凑件数开始编 | 白名单外的交付内容、越界材料一律拒绝登记 |

## 核心设计（五条不妥协的规则）

1. **每日件数 = 当天真实产出。** 没有日下限、没有日上限、没有「2~3 件/天」这种区间目标。干成一件就记一件，干出十件就记十件。月度件数只是这些真实工作自然累加的结果。
2. **工时每天必须报满 8h。** 件数不限，但工时是硬条件：低于 8h 的日子 `export-week` 直接拦截。常见区间 8~9h，长于 9h 也允许（真实即可），不设上限。
3. **多来源全部计入。** 我协助的、teleagent 跑的、AI Studio 出的、你手工做的，同一天合并成一份统计，并用「来源分布」把你看到的和实际记下的对齐。
4. **计数口径是「交付物件数」，不是「提交次数」。** 多数 OA 每周只能提交一次，按次数算一个月最多 4~5 次。
5. **周期按系统口径算，不按自然周。** 默认「上周六 → 本周五」，可配置；目录名用日期区间（`W_1017-1023`）而不是周序号，避免 ISO 周与业务周错位。

## 安装

### WorkBuddy / Claude Code 等支持 SKILL.md 的 Agent

```bash
git clone https://github.com/<you>/oa-workload.git ~/.workbuddy/skills/oa-workload
# 或 Claude Code：~/.claude/skills/oa-workload
```

Agent 读到 `SKILL.md` 就知道什么时候该调用它。

### 任意 Agent / 纯命令行

它本质就是一个零依赖的 Python CLI：

```bash
python scripts/oa.py --help
```

任何能执行 shell 的 Agent 都能用，只要在提示里告诉它「用 scripts/oa.py 记工时」。

## 配置（3 个文件）

```bash
cp config/settings.example.json     config/settings.json
cp config/projects.example.json     config/projects.json
cp config/dictionaries.example.json config/dictionaries.json
```

| 文件 | 填什么 |
|---|---|
| `settings.json` | 工作区路径、计数口径、参考线、周期模板、脱敏正则 |
| `projects.json` | 项目名/编号、成员、阶段划分 |
| `dictionaries.json` | **从你自己的系统里抄**：工作类型、事项清单、交付内容、交付物白名单 |

> ⚠️ `dictionaries.json` 不要凭语义猜。打开你的 OA 表单，把下拉项逐个抄下来。抄不到的宁可不填，脚本会提示「枚举未核对」。

## 用法

```bash
P="python scripts/oa.py"

$P status                                     # 今日件数/工时、本周、本月、来源分布、每日件数
$P init    --project <项目>                    # 建四级目录
$P log     --project <项目> --type <工作类型> \
           --source workbuddy \
           --entry "事项|工时|做了什么" \
           --deliverable "交付内容|数量|文件名"
$P audit   --month 2026-10                    # 核算（report 模式恒 exit 0）
$P export-week --project <项目>                # 出周提交包
$P rerender --project <项目>                   # 改附件名/格式后重渲染，不要重新 log
$P harvest --from <目录>                       # 扫存量产出，出候选清单（不自动登记）
```

`--entry` / `--deliverable` 都可以重复，一天多条一次写完。
`--source` 可选：`workbuddy`（默认）/ `teleagent` / `ai_studio` / `other_tool` / `manual`。

## 目录结构

```
<workspace>/
├── _ledger/ledger.jsonl              # 唯一真源（一行一次登记）
└── 2026-10/
    └── <项目>/
        ├── W_1017-1023/
        │   ├── 2026-10-20/
        │   │   ├── 当日填报.md          # 人读：清单类型 + 工时 + 交付物（含来源）+ 来源汇总
        │   │   └── 交付物/              # 实际要上传的文件
        │   └── _Weekly_Submit_Package/
        │       ├── 填报对照文本_xxx.txt
        │       └── 交付物清单_xxx.csv
        └── ...
```

`ledger.jsonl` 是唯一真源，其余全部由它渲染，删了能重生成。

## 计数口径与「参考线」

- 每日件数 = 当天台账里真实登记的可独立审查交付物数量（`Σ 交付物.数量`）。
- **`quota.sanity` 两个数字默认都是 0 = 不限**：单日件数、单交付内容件数都不设上限，真实工作量大就照实记。
- **每日工时是硬下限**：`workload_policy.min_daily_hours = 8.0`。本周任一天 < 8h → `export-week` exit 1，只写《工时不足提示.md》；`preferred_daily_hours = [8, 9]` 只用于提示，长于 9h 允许。
- `month_min` / `week_min` 是 **OA 的参考线**，只影响提示文案，不驱动每日生成。
- `quota.mode` 默认 `report`：`export-week` 照常出单，只在文本里提示「月累计 X 件，低于参考线」。
- 需要硬拦时显式改 `"mode": "strict"`：低于参考线则拒绝出单，只写《缺口预警单》。

## 它不会替你做的事

- 不会自动提交到 OA（多数 OA 无对外 API）
- 不会替你判断某份文件算不算交付物
- 不会为了凑数生成假文档，也不会为了「让数字好看」而把产出压缩或摊平。缺口就报缺口。

## License

MIT
