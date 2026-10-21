# -*- coding: utf-8 -*-
"""把交付物里的 .md 转成 .docx（md → HTML → Word 另存）。"""
import os, re, sys, html, glob, time
sys.stdout.reconfigure(encoding="utf-8")

CSS = """
body{font-family:"Microsoft YaHei","微软雅黑",sans-serif;font-size:10.5pt;line-height:1.65;color:#222}
h1{font-size:20pt;font-weight:600;margin:0 0 14pt}
h2{font-size:14pt;font-weight:600;margin:16pt 0 8pt;border-left:4px solid #2d6cdf;padding-left:8pt}
h3{font-size:12pt;font-weight:600;margin:12pt 0 6pt}
p{margin:0 0 8pt}
table{border-collapse:collapse;width:100%;margin:8pt 0;font-size:9.5pt}
th,td{border:1px solid #bbb;padding:4pt 6pt;vertical-align:top}
th{background:#eef3fb;font-weight:600}
ul,ol{margin:0 0 8pt 18pt;padding:0}
li{margin:0 0 3pt}
blockquote{margin:8pt 0;padding:6pt 10pt;background:#f6f7f9;border-left:3px solid #999;color:#444}
hr{border:none;border-top:1px solid #ddd;margin:12pt 0}
code{font-family:Consolas,monospace;background:#f2f2f2;padding:0 2pt}
sub{font-size:8pt;color:#666}
"""

def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', t)
    return t

def split_row(line):
    s = line.strip().strip("|")
    return [c.strip() for c in s.split("|")]

def md2html(md):
    lines = md.splitlines()
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if not s:
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append("<hr/>"); i += 1; continue

        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lv = len(m.group(1))
            out.append(f"<h{lv}>{inline(m.group(2))}</h{lv}>"); i += 1; continue

        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip()); i += 1
            out.append("<blockquote>" + "<br/>".join(inline(x) for x in buf) + "</blockquote>")
            continue

        if s.startswith("|") and i + 1 < n and re.match(r"^\|?[\s:\-|]+\|?$", lines[i + 1].strip()):
            head = split_row(s)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i])); i += 1
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>")
            for r in rows:
                r += [""] * (len(head) - len(r))
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r[:len(head)]) + "</tr>")
            out.append("</table>")
            continue

        if re.match(r"^[-*+]\s+", s):
            buf = []
            while i < n and re.match(r"^[-*+]\s+", lines[i].strip()):
                buf.append(re.sub(r"^[-*+]\s+", "", lines[i].strip())); i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in buf) + "</ul>")
            continue

        if re.match(r"^\d+[.)]\s+", s):
            buf = []
            while i < n and re.match(r"^\d+[.)]\s+", lines[i].strip()):
                buf.append(re.sub(r"^\d+[.)]\s+", "", lines[i].strip())); i += 1
            out.append("<ol>" + "".join(f"<li>{inline(x)}</li>" for x in buf) + "</ol>")
            continue

        buf = [s]
        i += 1
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,4}\s|\||>\s?|[-*+]\s|\d+[.)]\s|-{3,}$)", lines[i].strip()):
            buf.append(lines[i].strip()); i += 1
        out.append("<p>" + "<br/>".join(inline(x) for x in buf) + "</p>")

    return ('<html><head><meta charset="utf-8"><style>' + CSS + '</style></head><body>'
            + "\n".join(out) + "</body></html>")

def main(root):
    files = sorted(glob.glob(os.path.join(root, "**", "交付物", "*.md"), recursive=True))
    print(f"待转 {len(files)} 个")
    tmp = os.path.join(os.environ.get("TEMP", "."), "md2docx_tmp")
    os.makedirs(tmp, exist_ok=True)

    import win32com.client as win32
    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        word.Options.ConfirmConversions = False
    except Exception:
        pass

    ok = fail = 0
    for k, src in enumerate(files, 1):
        base = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(os.path.dirname(src), base + ".docx")
        htm = os.path.join(tmp, base + ".html")
        try:
            with open(src, encoding="utf-8") as f:
                md = f.read()
            with open(htm, "w", encoding="utf-8") as f:
                f.write(md2html(md))
            doc = word.Documents.Open(htm, ConfirmConversions=False, ReadOnly=False)
            # 让标题成为真正的 Heading 样式（HTML 导入会丢样式，只能按字号回填）
            WD_H = {-2: 18.0, -3: 13.5, -4: 11.8}
            try:
                for para in doc.Paragraphs:
                    try:
                        if para.Range.Tables.Count > 0:
                            continue
                        sz = float(para.Range.Font.Size or 0)
                        for lvl, th in WD_H.items():
                            if sz >= th:
                                para.Style = lvl
                                break
                    except Exception:
                        continue
            except Exception as e:
                print(f"    标题样式回填跳过: {e}")
            doc.SaveAs2(dst, FileFormat=16)
            doc.Close(False)
            ok += 1
            print(f"  [{k}/{len(files)}] OK  {base}.docx  ({os.path.getsize(dst)//1024} KB)")
        except Exception as e:
            fail += 1
            print(f"  [{k}/{len(files)}] FAIL {base}: {e}")
        finally:
            if os.path.exists(htm):
                try: os.remove(htm)
                except Exception: pass

    word.Quit()
    print(f"完成：成功 {ok}，失败 {fail}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
