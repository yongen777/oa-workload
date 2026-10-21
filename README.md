# oa-workload

把日常开发工作整理成**可直接填报进 OA 工时系统**的交付物台账 —— 按「项目 / 月 / 周 / 日」四级落档，按交付物数量做月度配额拦截，导出一份照着填的对照文本。

> 适用场景：公司要求每月提交 ≥N 个「研发过程文档类」交付物（需求记录、设计文档、功能模块代码、测试记录、部署手册……），但你真正的产出散在代码仓库、聊天记录和脑子里，月底才开始回忆。

---

## 它解决什么

| 痛点 | 做法 |
|---|---|
| 月底回忆这个月干了啥 | 每天一条 `log`，台账自动累积，随时可查 |
| 不知道这周够不够件数 | `audit` 当场算，不达标直接拒绝出单 |
| 填报时对着空表单发呆 | `export-week` 产出逐日明细 + 交付内容 + 附件清单，照着抄 |
| 交付物名和系统下拉对不上 | 字典配置 + 白名单硬校验，填错根本不让你登记 |
| 为了凑件数开始编 | 白名单外的交付内容、越界材料一律拒绝登记 |

## 核心设计（三条不妥协的规则）

1. **计数口径是「交付物件数」，不是「提交次数」。** 多数 OA 每周只能提交一次，按次数算一个月最多 4~5 次，配额必然不成立。
2. **周期按系统口径算，不按自然周。** 默认「上周六 → 本周五」，可配置；目录名用日期区间（`W_1017-1023`）而不是周序号，避免 ISO 周与业务周错位。
3. **登记时就要拦住脏数据，不是出单时再检查。** 白名单外的交付内容、非本项目的材料，`log` 直接拒绝。

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
| `settings.json` | 工作区路径、月度/周度配额、冒号周期模板、脱敏正则 |
| `projects.json` | 项目名/编号、成员、阶段划分 |
| `dictionaries.json` | **从你自己的系统里抄**：工作类型、事项清单、交付内容、交付物白名单 |

> ⚠️ `dictionaries.json` 不要凭语义猜。打开你的 OA 表单，把下拉项逐个抄下来。抄不到的宁可不填，脚本会提示「枚举未核对」。

## 用法

```bash
P="python scripts/oa.py"

$P status                                     # 这周第几天、月累计、闸门红绿
$P init    --project <项目>                    # 建四级目录
$P log     --project <项目> --type <工作类型> \
           --entry "事项|工时|做了什么" \
           --deliverable "交付内容|数量|文件名"
$P audit   --month 2026-10                    # 配额核算（exit 1 = 不达标）
$P export-week --project <项目>                # 出周提交包（不达标则拒绝）
$P harvest --from <目录>                       # 扫存量产出，出候选清单（不自动登记）
```

`--entry` / `--deliverable` 都可以重复，一天多条一次写完。

## 目录结构

```
<workspace>/
├── _ledger/ledger.jsonl              # 唯一真源（一行一次登记）
└── 2026-10/
    └── <项目>/
        ├── W_1017-1023/
        │   ├── 2026-10-20/
        │   │   ├── 当日填报.md          # 人读：清单类型 + 工时 + 交付物
        │   │   └── 交付物/              # 实际要上传的文件
        │   └── _Weekly_Submit_Package/
        │       ├── 填报对照文本_xxx.txt
        │       └── 交付物清单_xxx.csv
        └── ...
```

`ledger.jsonl` 是唯一真源，其余全部由它渲染，删了能重生成。

## 配额闸门怎么工作

- 周底线 `week_min`（默认 8 件），月底线 `month_min`（默认 30 件）
- 当月期望 = `min(week_min × 本月已收口周数, month_min)`
- `export-week` 先算后出：不达标**不生成填报文本**，只写《缺口预警单》，退出码 1
- 想改成「照出但标黄」：`quota.mode = "warn"`（但这条例约束就软了）

## 它不会替你做的事

- 不会自动提交到 OA（多数 OA 无对外 API）
- 不会替你判断某份文件算不算交付物
- 不会为了凑数生成假文档。缺口就报缺口。

## License

MIT
