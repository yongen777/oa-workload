#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云中台OA工时台账 CLI —— stdlib only。

除 xlsx 导出外无第三方依赖；未安装 openpyxl 时自动降级 CSV（OA 只收 xls/xlsx，
降级后须用 WPS 另存，脚本会明确提示）。

用法见 SKILL.md；`oa.py <cmd> -h` 有逐条参数说明。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("OA_WORKLOAD_CONFIG") or (SKILL_DIR / "config"))

EXIT_OK, EXIT_QUOTA, EXIT_CONFIG = 0, 1, 2
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ---------------------------------------------------------------- 基础设施

def _u(*a, **kw):
    print(*a, **kw)


def die(msg: str, code: int = EXIT_CONFIG):
    _u(msg, file=sys.stderr)
    sys.exit(code)


def load_json(path: Path, what: str, default=None):
    if not path.exists():
        if default is not None:
            return default
        die(
            f"[配置缺失] 找不到 {path}\n"
            f"请先复制 config/*.example.json 为正式配置并填写（{what}）。"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"[配置损坏] {path} 不是合法 JSON：{e}")


def settings() -> dict:
    return load_json(CONFIG_DIR / "settings.json", "settings")


def dictionaries() -> dict:
    return load_json(
        CONFIG_DIR / "dictionaries.json",
        "dictionaries",
        default={"work_types": [], "items": [], "deliverable_contents": []},
    )


def projects() -> dict:
    cfg = load_json(CONFIG_DIR / "projects.json", "projects")
    out = {}
    for p in cfg.get("projects", []):
        code = (p.get("code") or "").strip()
        # 允许 code 为空：真实项目编号等用户提供，空值走「_待命名项目」占位目录
        out[code or "__pending__"] = p
    return out


def slug_of(p: dict) -> str:
    code = (p.get("code") or "").strip()
    short = (p.get("short") or "").strip()
    if code:
        return f"{code}_{short}" if short else code
    return "_待命名项目" + (f"_{short}" if short else "")


def resolve_project(key: str | None) -> dict:
    allp = projects()
    if not allp:
        die("[项目未配置] projects.json 是空的，至少留一个条目（code 可空）。")
    if not key:
        if len(allp) == 1:
            return next(iter(allp.values()))
        die("[需要 --project] 有多个项目：" + ", ".join(allp))
    if key in allp:
        return allp[key]
    hit = [p for c, p in allp.items()
           if c.startswith(key) or key in (p.get("short") or "") or key == p.get("code")]
    if len(hit) == 1:
        return hit[0]
    if not hit:
        die(f"[未知项目] {key} 不在 projects.json 里。已配：" + ", ".join(allp))
    die(f"[项目歧义] {key} 命中多个：" + ", ".join(p.get("code") or "【待补】" for p in hit))


# ---------------------------------------------------------------- 周期口径

def oa_week(d: dt.date):
    """OA 周 = 上周六 ~ 本周五（手册 P54 / image16 界面红字）。"""
    back = (d.weekday() - 5) % 7          # 周六=5；回退到最近的周六
    start = d - dt.timedelta(days=back)
    return start, start + dt.timedelta(days=6)


def fmt(tpl: str, s: dt.date, e: dt.date) -> str:
    try:
        return tpl.format(s=s, e=e, **{"": None})
    except (KeyError, IndexError):
        die(f"[配置错误] paths.week_label 模板不合法：{tpl}（可用 {{s:%m%d}} / {{e:%m%d}}）")


def week_label(d: dt.date) -> str:
    s, e = oa_week(d)
    return fmt(settings()["paths"]["week_label"], s, e)


def workspace_root() -> Path:
    root = (settings().get("workspace_root") or "").strip()
    if not root:
        die(
            "[未初始化] settings.json 的 workspace_root 是空的。\n"
            "这是你的主工作文件夹（例：D:/OA_Workspace），填好再跑。"
        )
    p = Path(root)
    if not p.exists():
        die(f"[路径不存在] workspace_root = {p}")
    return p


def project_dir(p: dict, d: dt.date) -> Path:
    return (
        workspace_root()
        / settings()["paths"]["month_label"].format(d)
        / slug_of(p)
        / week_label(d)
    )


def ledger_path() -> Path:
    cfg = settings()["paths"]
    base = workspace_root()
    if cfg.get("ledger_in_project"):
        pl = projects()
        if pl:
            base = base / slug_of(next(iter(pl.values())))
    return base / cfg.get("ledger_dir", "_ledger") / "ledger.jsonl"


def read_ledger() -> list[dict]:
    lp = ledger_path()
    if not lp.exists():
        return []
    rows = []
    for line in lp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_ledger(entry: dict):
    lp = ledger_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    with lp.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 配额

def month_bounds(month: str):
    y, m = (int(x) for x in month.split("-"))
    start = dt.date(y, m, 1)
    end = (dt.date(y + (m == 12), (m % 12) + 1, 1)) - dt.timedelta(days=1)
    return start, end


def oa_weeks_in(start: dt.date, end: dt.date):
    """落在 [start, end] 内的所有 OA 周（以周六为键）。"""
    s, _ = oa_week(start)
    out = []
    while s <= end:
        out.append((s, s + dt.timedelta(days=6)))
        s += dt.timedelta(days=7)
    return out


def qty_of(entry: dict) -> int:
    return sum(int(x.get("qty") or 0) for x in entry.get("deliverables", []))


def audit(month: str, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    cfg = settings()
    month_min = int(cfg["quota"]["month_min"])
    week_min = int(cfg["quota"]["week_min"])
    m_start, m_end = month_bounds(month)

    rows = [r for r in read_ledger() if m_start <= dt.date.fromisoformat(r["date"]) <= m_end]
    month_total = sum(qty_of(r) for r in rows)

    ws, we = oa_week(today)
    week_total = sum(qty_of(r) for r in rows if ws <= dt.date.fromisoformat(r["date"]) <= we)

    # 口径：当月 = 按已过周数递进；已过月份 = 按整月 30 件结算；未来月份 = 不设闸
    cur_month = today.strftime("%Y-%m")
    is_current = month == cur_month
    is_past = month < cur_month
    all_weeks = oa_weeks_in(m_start, m_end)

    if is_current:
        elapsed = [w for w in all_weeks if w[1] <= today]
        expected = min(week_min * len(elapsed), month_min) if elapsed else 0
    elif is_past:
        elapsed = all_weeks
        expected = month_min
    else:
        elapsed = []
        expected = 0

    per_project: dict[str, int] = {}
    for r in rows:
        per_project[r["project"]] = per_project.get(r["project"], 0) + qty_of(r)

    reasons = []
    if month_total < expected:
        tag = "应达" if is_current else "整月应达"
        reasons.append(f"月度累计 {month_total} 件 < {tag} {expected} 件（差 {expected - month_total}）")
    if is_current and elapsed and week_total < week_min:
        reasons.append(f"本周 {week_total} 件 < 周底线 {week_min} 件（差 {week_min - week_total}）")

    return {
        "month": month,
        "month_total": month_total,
        "month_min": month_min,
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "week_total": week_total,
        "week_min": week_min,
        "elapsed_weeks": len(elapsed),
        "expected_now": expected,
        "per_project": per_project,
        "blocked": bool(reasons),
        "reasons": reasons,
    }


# ---------------------------------------------------------------- 命令

def cmd_status(a):
    today = dt.date.today()
    s, e = oa_week(today)
    cfg = settings()
    _u("=" * 62)
    _u(f"今天        {today}  {WEEKDAY_CN[today.weekday()]}")
    _u(f"当前 OA 周  {s} ~ {e}   →  目录名 {week_label(today)}")
    root = (cfg.get("workspace_root") or "").strip()
    _u(f"工作区      {root or '⚠️ 未配置 workspace_root'}")
    _u(f"队伍档位    {cfg.get('profile')}   闸门模式 {cfg.get('quota', {}).get('mode')}")
    try:
        rep = audit(today.strftime("%Y-%m"))
    except SystemExit:
        _u("=" * 62)
        return
    _u("-" * 62)
    _u(f"本月累计    {rep['month_total']} / {rep['month_min']} 件   "
       f"（已过 {rep['elapsed_weeks']} 个 OA 周，本周应达 {rep['expected_now']} 件）")
    _u(f"本周累计    {rep['week_total']} / {rep['week_min']} 件")
    if rep["per_project"]:
        _u("分项目：")
        for code, n in sorted(rep["per_project"].items(), key=lambda kv: -kv[1]):
            _u(f"  - {code}: {n}")
    _u("-" * 62)
    _u("闸门状态    " + ("🔴 已拦截（" + "；".join(rep["reasons"]) + "）" if rep["blocked"] else "🟢 可出单"))
    _u("=" * 62)


def cmd_init(a):
    p = resolve_project(a.project)
    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    base = project_dir(p, d)
    day = base / settings()["paths"]["date_label"].format(d)
    pkg = base / settings()["paths"].get("weekly_package_dir", "_Weekly_Submit_Package")
    for x in (day, pkg):
        x.mkdir(parents=True, exist_ok=True)
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    _u(f"✅ 目录就绪\n   {day}\n   {pkg}")
    if not (CONFIG_DIR / "projects.json").exists():
        _u("⚠️ projects.json 还没建，先 cp 样例再跑一次")


def _parse_deliv(s: str) -> dict:
    parts = [x.strip() for x in s.split("|")]
    if len(parts) < 2:
        die(f"[格式错误] --deliverable 需要三段：交付内容|数量|文件名，收到：{s}")
    content = parts[0]
    try:
        qty = int(float(parts[1] or 0))
    except ValueError:
        die(f"[格式错误] 数量必须是数字，收到：{parts[1]}")
    return {"content": content, "qty": qty, "file": parts[2] if len(parts) > 2 else ""}


def _parse_entry(s: str) -> dict:
    parts = [x.strip() for x in s.split("|")]
    if len(parts) < 3:
        die(f"[格式错误] --entry 需要三段：事项清单|时长|工作内容描述，收到：{s}")
    try:
        hours = float(parts[1] or 0)
    except ValueError:
        die(f"[格式错误] 时长必须是数字，收到：{parts[1]}")
    return {"item": parts[0], "hours": hours, "desc": parts[2]}


def cmd_log(a):
    p = resolve_project(a.project)
    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    types = a.type or []
    entries = [_parse_entry(x) for x in (a.entry or [])]
    delivs = [_parse_deliv(x) for x in (a.deliverable or [])]
    if not entries and not delivs:
        die("至少要给一条 --entry 或 --deliverable")

    dic = dictionaries()
    warn = []
    for t in types:
        if dic.get("work_types") and t not in dic["work_types"]:
            warn.append(f"工作类型「{t}」不在 dictionaries.work_types 里")
    for e in entries:
        if dic.get("items") and e["item"] not in dic["items"]:
            warn.append(f"事项清单「{e['item']}」不在 dictionaries.items 里")
    # 交付内容 = 硬闸门：只认 P87 软研白名单 15 项（或对应队伍白名单）
    wl = (dic.get("soft_dev_whitelist") if settings().get("profile") == "soft_dev"
          else dic.get("deliverable_contents")) or []
    if wl:
        for dv in delivs:
            if dv["content"] not in wl:
                die(
                    f"[拒绝登记] 交付内容「{dv['content']}」不在软研队伍白名单内。\n"
                    f"  可用值：{'、'.join(wl)}\n"
                    f"  依据：云中台OA操作手册 P87（新增/修改的研发过程文档 15 类）。\n"
                    f"  与项目无关的材料（如工时台账整理、OA 填报核对）一律不得登记为项目交付物。"
                )

    sanity = settings().get("quota", {}).get("sanity", {})
    cap_d = int(sanity.get("max_qty_per_day", 12))
    if sum(x["qty"] for x in delivs) > cap_d:
        die(f"[异常] 单日交付物合计 {sum(x['qty'] for x in delivs)} 件 > 上限 {cap_d}，疑似凑数，拒绝登记。")
    for x in delivs:
        if x["qty"] > int(sanity.get("max_files_per_deliverable", 5)):
            die(f"[异常] 单一交付内容「{x['content']}」数量 {x['qty']} > 上限，疑似拆附件凑数。")

    pats = [re.compile(x) for x in settings().get("desensitize", {}).get("patterns", [])]
    hits = set()
    for blob in [e["desc"] for e in entries] + [x["file"] for x in delivs]:
        for rp in pats:
            hits.update(rp.findall(blob))

    entry = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "date": d.isoformat(),
        "week": week_label(d),
        "project": p["code"],
        "work_types": types,
        "entries": entries,
        "deliverables": delivs,
        "qty": sum(x["qty"] for x in delivs),
        "source": a.source or "manual",
    }
    append_ledger(entry)
    _write_day(p, d)

    _u(f"✅ 已登记  {d}  {p['code']}  工时 {sum(e['hours'] for e in entry['entries']):.1f}h  交付物 {entry['qty']} 件")
    _u(f"   台账 {ledger_path()}")
    for w in warn:
        _u(f"   ⚠️ 枚举未校验：{w}")
    if hits:
        _u(f"   🔒 脱敏命中（上传前务必处理）：{sorted(hits)}")


def _write_day(p: dict, d: dt.date) -> Path:
    """按台账聚合渲染某天的「当日填报.md」，返回日目录。log 与 rerender 共用。"""
    day = project_dir(p, d) / settings()["paths"]["date_label"].format(d)
    day.mkdir(parents=True, exist_ok=True)
    (day / "交付物").mkdir(exist_ok=True)

    logs = [r for r in read_ledger()
            if r.get("project") == p["code"] and r.get("date") == d.isoformat()]
    types, entries, delivs = [], [], []
    for lg in logs:
        for t in (lg.get("work_types") or []):
            if t not in types:
                types.append(t)
        entries += lg.get("entries") or []
        delivs += lg.get("deliverables") or []
    total_h = sum(e.get("hours", 0) for e in entries)
    total_q = sum(int(dv.get("qty") or 0) for dv in delivs)

    M = []
    M.append(f"# {d} {WEEKDAY_CN[d.weekday()]} · 当日填报")
    M.append("")
    M.append(f"> 项目：{p.get('name') or p['code']}｜周次 `{week_label(d)}`｜生成 {dt.datetime.now():%H:%M}")
    M.append("")
    M.append("## 一、清单类型（OA「工作类型」，可多选）")
    M.append("")
    for t in (types or ["【待补】"]):
        M.append(f"- `{t}`")
    M.append("")
    M.append("## 二、工时明细（OA「事项清单 + 工时」）")
    M.append("")
    M.append("| 事项清单 | 时长(h) | 工作内容描述 |")
    M.append("|---|---|---|")
    for e in entries:
        M.append(f"| {e['item']} | {e['hours']:g} | {e['desc']} |")
    M.append(f"| **合计** | **{total_h:g}** | |")
    M.append("")
    M.append("## 三、交付物基础信息（OA「交付内容 + 数量 + 附件」）")
    M.append("")
    M.append("| # | 交付内容 | 数量 | 附件 |")
    M.append("|---|---|---|---|")
    for i, dv in enumerate(delivs, 1):
        M.append(f"| {i} | {dv['content']} | {dv.get('qty', 0)} | {dv.get('file') or '—'} |")
    M.append(f"| | **合计** | **{total_q}** | |")
    M.append("")
    M.append("## 四、怎么填进 OA")
    M.append("")
    M.append(f"1. 「本周工时录入」{d} 那行：工作类型选上表清单类型，事项清单按第二节逐行填，工时照填")
    M.append("2. 底部「基础信息」：事项清单选全，交付内容按第三节选，数量按第三节")
    M.append(f"3. 附件从本目录 `交付物\\` 取（{total_q} 件）")
    M.append("4. ⚠️ 交付物请脱敏后上传")
    (day / "当日填报.md").write_text("\n".join(M) + "\n", encoding="utf-8")
    return day


def cmd_rerender(a):
    """按台账重渲染所有「当日填报.md」（改了附件名/文件名后用它，不要重新 log）。"""
    p = resolve_project(a.project)
    dates = sorted({r["date"] for r in read_ledger() if r.get("project") == p["code"]})
    if a.date:
        dates = [x for x in dates if x == a.date]
    for ds in dates:
        day = _write_day(p, dt.date.fromisoformat(ds))
        _u(f"  ✅ {ds}  {day}")
    _u(f"重渲染 {len(dates)} 天")


def cmd_audit(a):
    month = a.month or dt.date.today().strftime("%Y-%m")
    rep = audit(month)
    _u(json.dumps(rep, ensure_ascii=False, indent=2))
    sys.exit(EXIT_QUOTA if rep["blocked"] else EXIT_OK)


def _gap_note(rep: dict, p: dict) -> str:
    gap_m = max(0, rep["expected_now"] - rep["month_total"])
    gap_w = max(0, rep["week_min"] - rep["week_total"])
    return f"""# 交付物缺口预警单

> 本工具已**锁定本次出单**（`quota.mode = block`）。补足后重跑 `export-week` 即可。

| 项 | 实际 | 应达 | 缺口 |
|---|---|---|---|
| 月度累计（{rep['month']}） | {rep['month_total']} 件 | {rep['expected_now']} 件 | **{gap_m} 件** |
| 本周（{rep['week_start']} ~ {rep['week_end']}） | {rep['week_total']} 件 | {rep['week_min']} 件 | **{gap_w} 件** |
| 月底线 | {rep['month_total']} 件 | {rep['month_min']} 件 | {max(0, rep['month_min'] - rep['month_total'])} 件 |

**拦截原因**
""" + "\n".join(f"- {r}" for r in rep["reasons"]) + f"""

## 合规补齐路径（只登记真实产物，禁止虚构）

1. `harvest` 扫存量：`oa.py harvest --from "<目录>" --project {p['code']}`
   —— 只出候选清单，你人工勾选后再 `log`。
2. 按软研白名单（手册 P87）逐类核对今天/本周到底产出了什么：

| 类别 | 常见实际产物 | 交付内容填法 |
|---|---|---|
| 需求 | 需求记录、调研纪要 | 需求记录 |
| 设计 | 系统设计/数据库设计/功能设计文档 | 功能设计文档 |
| 代码 | 功能模块代码包 | 功能模块代码 |
| 测试 | 测试方案/用例/记录 | 测试用例 |
| 文档 | 培训文档、支撑清单、部署手册、问题处理手册 | 软件部署手册 |

3. 一份文档 = 1 件（或系统里对应的交付内容行数量）。**不要**把一份文档拆成多个空附件——`sanity` 校验会直接拒绝。

## 手工登记示例

```
oa.py log --project {p['code']} \\
  --type 研发 --entry "功能设计文档|3.5|完成XX模块设计说明第1-3章" \\
  --deliverable "功能设计文档|1|20261021_XX设计说明书_v1.0.docx"
```
"""


def cmd_export_week(a):
    p = resolve_project(a.project)
    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    ws, we = oa_week(d)
    label = week_label(d)
    base = project_dir(p, d)
    pkg = base / settings()["paths"].get("weekly_package_dir", "_Weekly_Submit_Package")
    pkg.mkdir(parents=True, exist_ok=True)

    rep = audit(d.strftime("%Y-%m"), today=d)
    mode = settings()["quota"].get("mode", "block")
    if rep["blocked"] and mode == "block" and not a.force:
        note = pkg / "缺口预警单.md"
        note.write_text(_gap_note(rep, p), encoding="utf-8")
        _u(f"🔴 出单已拦截 —— 未达配额。缺口清单：\n   {note}")
        for r in rep["reasons"]:
            _u(f"   · {r}")
        _u("   补足后重跑；确需强制出单加 --force（会在文本里打红标）。")
        sys.exit(EXIT_QUOTA)

    rows = [
        r for r in read_ledger()
        if r["project"] == p["code"] and ws <= dt.date.fromisoformat(r["date"]) <= we
    ]
    rows.sort(key=lambda r: r["date"])

    dic = dictionaries()
    has_dict = bool(dic.get("work_types") or dic.get("items") or dic.get("deliverable_contents"))
    verified = dic.get("_verified") is True
    unverified = (not has_dict) or (not verified)

    L = []
    L.append("=" * 68)
    L.append("【云中台OA 工时填报对照文本】")
    L.append("=" * 68)
    L.append(f"项目名称：{p.get('name') or '【待补】'}")
    L.append(f"项目编号：{p['code']}")
    L.append(f"部门小组：{p.get('group') or '【待补】'}      组长：{p.get('leader') or '【待补】'}")
    L.append(f"填报周期：{ws} ~ {we}（上周六~本周五，系统周区间：{ws} - {we}）")
    L.append("")
    if rep["blocked"] or unverified:
        L.append("!" * 68)
        if rep["blocked"]:
            L.append("!! 配额未达标，本单为强制出单，存在被组长退回风险：")
            for r in rep["reasons"]:
                L.append(f"!!   · {r}")
        if unverified:
            if has_dict:
                L.append("!! 枚举未经系统核对（dictionaries.json 的 _verified = false）：")
                L.append("!! 工作类型/事项清单/交付内容 三组值里有自拟项，粘贴前请在系统下拉里逐个对照，")
                L.append("!! 名字不一致就以系统为准，回头改字典再置 _verified = true。")
            else:
                L.append("!! 枚举未配置：dictionaries.json 是空的，三组下拉值完全没有来源。")
                L.append("!! 粘贴前必须先在系统里抄一遍下拉项，勿盲贴。")
        L.append("!" * 68)
        L.append("")

    L.append("-" * 68)
    L.append("【逐日明细】对应系统「本周工时录入」——每天一行（同一天多次登记已自动合并）")
    L.append("-" * 68)
    by_day: dict[str, list] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    for date_s, rs in sorted(by_day.items()):
        day = dt.date.fromisoformat(date_s)
        types: list[str] = []
        for r in rs:
            for t in (r.get("work_types") or []):
                if t not in types:
                    types.append(t)
        entries = [e for r in rs for e in (r.get("entries") or [])]
        L.append(f"{day}  {WEEKDAY_CN[day.weekday()]}")
        L.append(f"  工作类型：{'、'.join(types) or '【待补】'}")
        if entries:
            L.append("  明细：")
            for e in entries:
                L.append(f"    - {e['item']} | {e['hours']}h | {e['desc']}")
            L.append(f"  小计：{sum(e['hours'] for e in entries):.1f}h")
        L.append("")

    items, contents, files = {}, {}, []
    for r in rows:
        for e in r.get("entries", []):
            items[e["item"]] = items.get(e["item"], 0) + e["hours"]
        for dv in r.get("deliverables", []):
            contents[dv["content"]] = contents.get(dv["content"], 0) + dv["qty"]
            if dv.get("file"):
                files.append((r["date"], dv["content"], dv["qty"], dv["file"]))

    L.append("-" * 68)
    L.append("【基础信息】事项清单 / 交付内容（对应表单底部两个下拉）")
    L.append("-" * 68)
    L.append("  事项清单：" + ("；".join(f"{k}({v:g}h)" for k, v in items.items()) or "【待补】"))
    L.append("  交付内容：" + ("；".join(contents) or "【待补】"))
    L.append("")
    L.append("-" * 68)
    L.append("【交付内容与附件】对应「交付内容 | 数量* | 附件」表格（系统自动统计数量）")
    L.append("-" * 68)
    for i, (k, v) in enumerate(contents.items(), 1):
        L.append(f"  {i}. {k}   数量 {v}")
        for d0, c0, q0, f0 in files:
            if c0 == k:
                L.append(f"       └ {d0}  {q0} 件  {f0}")
    L.append("")
    L.append("-" * 68)
    L.append(f"  本周交付物合计：{sum(contents.values())} 件")
    L.append(f"  本月累计：{rep['month_total']} / {rep['month_min']} 件")
    L.append("-" * 68)
    L.append("⚠️ 交付物请脱敏后上传，请勿直接上传涉密文件及敏感数据（系统界面原文）")
    L.append("⚠️ 工作内容描述必须填写，要尽可能的详细（系统界面原文）")
    L.append("⚠️ 本文件只是对照文本，最终「提交」需你在系统里手工点击并确认。")
    L.append("=" * 68)

    txt = pkg / f"填报对照文本_{label}.txt"
    txt.write_text("\n".join(L), encoding="utf-8")

    csvp = pkg / f"交付物清单_{label}.csv"
    with csvp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "项目编号", "交付内容", "数量", "附件文件名", "是否脱敏"])
        for d0, c0, q0, f0 in files:
            w.writerow([d0, p["code"], c0, q0, f0, "待确认"])

    _u(f"✅ 出单完成\n   {txt}\n   {csvp}")
    _u(f"   本周 {sum(contents.values())} 件 · 本月 {rep['month_total']}/{rep['month_min']} 件")
    if unverified:
        _u("   ⚠️ " + ("字典已填但未经系统核对" if has_dict else "字典为空") + "，文本里已打横幅")


# ---------------------------------------------------------------- 项目简介

PH = "【待补】"

DEFAULT_STAGES = [
    ("需求 / 调研", "需求记录、需求设计文档"),
    ("设计", "系统设计、数据库设计、功能设计文档"),
    ("开发", "功能模块代码"),
    ("测试", "测试方案、测试用例、测试记录"),
    ("交付", "软件部署手册、问题处理手册、培训文档"),
]


def _need(v, hint: str = "") -> str:
    v = (v or "").strip() if isinstance(v, str) else v
    return v if v else f"{PH}{hint}"


def _member_txt(m) -> str:
    if isinstance(m, dict):
        name = (m.get("name") or PH).strip()
        role = (m.get("role") or "").strip()
        return f"{name}（{role}）" if role else name
    return str(m).strip() or PH


def cmd_brief(a):
    """生成给组长看的「项目简介文本」。只由 projects.json + 台账推导，不编事实。"""
    p = resolve_project(a.project)
    root = (workspace_root()
            / settings()["paths"]["month_label"].format(dt.date.today())
            / slug_of(p))
    root.mkdir(parents=True, exist_ok=True)
    b = p.get("brief") or {}
    today = dt.date.today()
    month = a.month or today.strftime("%Y-%m")

    m_start, m_end = month_bounds(month)
    rows = [r for r in read_ledger()
            if r.get("project") == p["code"]
            and m_start <= dt.date.fromisoformat(r["date"]) <= m_end]
    qty_month = sum(qty_of(r) for r in rows)
    ws, we = oa_week(today)
    qty_week = sum(qty_of(r) for r in rows
                   if ws <= dt.date.fromisoformat(r["date"]) <= we)

    contents: dict[str, int] = {}
    items: dict[str, float] = {}
    for r in sorted(rows, key=lambda x: x["date"]):
        for dv in r.get("deliverables", []):
            contents[dv["content"]] = contents.get(dv["content"], 0) + dv["qty"]
        for e in r.get("entries", []):
            items[e["item"]] = items.get(e["item"], 0) + e["hours"]

    members = [_member_txt(m) for m in (p.get("members") or [])] or [f"{PH}（姓名须与系统内完全一致）"]
    stages = b.get("stages") or [{"stage": s, "deliverables": d} for s, d in DEFAULT_STAGES]

    L = []
    L.append(f"# 项目简介｜{_need(p.get('name'))}")
    L.append("")
    L.append(f"> 生成 {dt.datetime.now():%Y-%m-%d %H:%M}｜数据来源：`projects.json` + 台账 `_ledger/ledger.jsonl`")
    L.append("> 标 `【待补】` 的必须人工补齐；标 `（草稿·待定稿）` 的是代拟段落，外发前须你改定。")
    L.append("")
    L.append("## 一、基本信息")
    L.append("")
    L.append("| 项 | 内容 |")
    L.append("|---|---|")
    L.append(f"| 项目名称 | {_need(p.get('name'))} |")
    L.append(f"| 项目编号 | {_need(p.get('code'))} |")
    L.append(f"| 编号来源 | {_need(p.get('source'))} |")
    L.append(f"| 部门小组 | {_need(p.get('group'), '（须与系统内小组名逐字一致）')} |")
    L.append(f"| 项目负责人（组长） | {_need(p.get('leader'))} |")
    L.append(f"| 客户 | {_need(p.get('client'))} |")
    L.append(f"| 行业 | {_need(p.get('industry'))} |")
    L.append(f"| 项目状态 | {_need(p.get('status'))} |")
    L.append(f"| 成员 | {'；'.join(members)} |")
    L.append("")
    L.append("## 二、项目背景与目标")
    L.append("")
    L.append(b.get("background") or f"{PH}：一句话说明「为什么做这个项目、解决什么问题」。{PH}说明目标（可验收的形态）。")
    L.append("")
    L.append("## 三、工作范围")
    L.append("")
    L.append(b.get("scope") or f"{PH}：列出本项目做什么（3~5 条），以及明确不做什么。")
    if b.get("out_of_scope"):
        L.append("")
        L.append("**不含**：" + b["out_of_scope"])
    L.append("")
    L.append("## 四、阶段与产出")
    L.append("")
    L.append("| 阶段 | 主要交付物 |")
    L.append("|---|---|")
    for s in stages:
        if isinstance(s, dict):
            L.append(f"| {s.get('stage') or PH} | {s.get('deliverables') or PH} |")
        else:
            L.append(f"| {s} | {PH} |")
    L.append("")
    L.append("## 五、当前进展（台账统计，非估算）")
    L.append("")
    L.append(f"- 统计月 **{month}**：已登记交付物 **{qty_month}** 件（月底线 30 件）")
    L.append(f"- 本周（{ws} ~ {we}）：**{qty_week}** 件（周底线 8 件）")
    if contents:
        L.append("- 交付内容分布：")
        for k, v in sorted(contents.items(), key=lambda kv: -kv[1]):
            L.append(f"  - {k}：{v} 件")
    else:
        L.append(f"- 交付内容分布：{PH}（本月台账尚无登记）")
    if items:
        L.append("- 工作量分布：" + "；".join(f"{k} {v:g}h" for k, v in sorted(items.items(), key=lambda kv: -kv[1])))
    L.append("")
    L.append("## 六、外发前检查")
    L.append("")
    L.append("- [ ] 客户全称、小组名已与系统核对（写错会导入/上报失败）")
    L.append("- [ ] 无内网 IP / 账号 / 手机号 / 密钥（本文件生成时已做一次自动扫描，见下方提示）")
    L.append("- [ ] `【待补】` 已全部补齐")
    L.append("")

    text = "\n".join(L)
    hits = []
    for pat in settings().get("desensitize", {}).get("patterns", []):
        try:
            hits += re.findall(pat, text)
        except re.error:
            pass
    if hits:
        text += "\n> 🔒 脱敏命中（外发前务必处理）：" + "、".join(sorted(set(hits))) + "\n"

    out = Path(a.out) if a.out else root / f"_项目简介_{(p.get('code') or '待命名').strip()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    missing = []
    for label, val in [("项目名称", p.get("name")), ("编号来源", p.get("source")),
                       ("部门小组", p.get("group")), ("组长", p.get("leader")),
                       ("客户", p.get("client")), ("行业", p.get("industry")),
                       ("背景与目标", b.get("background")), ("工作范围", b.get("scope"))]:
        if not (val or "").strip() if isinstance(val, str) else not val:
            missing.append(label)

    _u(f"✅ 已生成 {out}")
    _u(f"   {month} 累计 {qty_month} 件 · 本周 {qty_week} 件 · 成员 {len(p.get('members') or [])} 人")
    if missing:
        _u("   ⚠️ 仍是占位符：" + "、".join(missing))
    if hits:
        _u("   🔒 脱敏命中：" + "、".join(sorted(set(hits))))


# ---------------------------------------------------------------- 存量挖掘

GUESS = [
    ("方案", "产品方案"), ("设计", "功能设计文档"), ("需求", "需求记录"),
    ("测试", "测试用例"), ("用例", "测试用例"), ("报告", "测试记录"),
    ("纪要", "沟通会议纪要+拜访照片"), ("周报", "支撑清单"),
    ("手册", "软件部署手册"), ("接口", "功能设计文档"), ("部署", "软件部署手册"),
]
EXTS = {".docx", ".doc", ".pdf", ".md", ".xlsx", ".xls", ".pptx", ".zip", ".png", ".jpg"}


def cmd_harvest(a):
    src = Path(a.from_dir)
    if not src.exists():
        die(f"[路径不存在] {src}")
    registered = set()
    for r in read_ledger():
        for dv in r.get("deliverables", []):
            if dv.get("file"):
                registered.add(Path(dv["file"]).name)

    cands = []
    for f0 in src.rglob("*"):
        if not f0.is_file() or f0.suffix.lower() not in EXTS:
            continue
        if any(part.startswith("_") or part == ".workbuddy" for part in f0.parts):
            continue
        if a.since and f0.stat().st_mtime < dt.datetime.fromisoformat(a.since).timestamp():
            continue
        guess = "【待你判定】"
        for kw, content in GUESS:
            if kw in f0.name:
                guess = content
                break
        cands.append([
            f0.name, str(f0.parent), f"{f0.stat().st_size/1024:.0f}KB",
            dt.datetime.fromtimestamp(f0.stat().st_mtime).strftime("%Y-%m-%d"),
            guess, "已登记" if f0.name in registered else "未登记",
        ])

    cands.sort(key=lambda r: r[3], reverse=True)
    out = Path(a.out) if a.out else (Path.cwd() / "harvest_候选交付物.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["文件名", "所在目录", "大小", "修改日期", "猜测交付内容(需人工确认)", "登记状态"])
        w.writerows(cands)
    _u(f"✅ 候选 {len(cands)} 个 → {out}")
    _u("   ⚠️ 只出清单，未登记任何东西。「猜测交付内容」是关键词命中，必须你逐条改。")
    _u("   挑完后用 log --deliverable \"交付内容|1|文件名\" 逐条登记。")


# ---------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(prog="oa.py", description="云中台OA工时台账")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="当前周/月/闸门概览"); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("init", help="建四级目录")
    s.add_argument("--project"); s.add_argument("--date"); s.set_defaults(fn=cmd_init)

    s = sub.add_parser("log", help="登记某天工时与交付物")
    s.add_argument("--project"); s.add_argument("--date")
    s.add_argument("--type", action="append", help="工作类型，可重复")
    s.add_argument("--entry", action="append", help='事项清单|时长|工作内容描述，可重复')
    s.add_argument("--deliverable", action="append", help='交付内容|数量|文件名，可重复')
    s.add_argument("--source", default="manual")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("rerender", help="按台账重渲染当日填报（改文件名后用）")
    s.add_argument("--project"); s.add_argument("--date"); s.set_defaults(fn=cmd_rerender)

    s = sub.add_parser("audit", help="配额核算")
    s.add_argument("--month"); s.set_defaults(fn=cmd_audit)

    s = sub.add_parser("export-week", help="出周提交包（先过闸门）")
    s.add_argument("--project"); s.add_argument("--date")
    s.add_argument("--force", action="store_true", help="未达标也强行出单（文本打红条）")
    s.set_defaults(fn=cmd_export_week)

    s = sub.add_parser("brief", help="生成给组长看的项目简介文本")
    s.add_argument("--project"); s.add_argument("--month"); s.add_argument("--out")
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("harvest", help="扫存量产出，出候选清单（不登记）")
    s.add_argument("--from", dest="from_dir", required=True)
    s.add_argument("--project"); s.add_argument("--since", help="ISO 日期，只要改过的")
    s.add_argument("--out"); s.set_defaults(fn=cmd_harvest)

    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    a.fn(a)


if __name__ == "__main__":
    main()
