# -*- coding: utf-8 -*-
"""把本项目书的 Markdown 转为带样式的 HTML（供 html-to-docx 转换）。
仅处理本项目书用到的语法子集：标题/表格/代码块/有序无序列表/blockquote/hr/粗体/行内代码。
"""
import re
import sys
import html as h


def inline(text: str) -> str:
    text = h.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def parse_table(rows):
    # 去掉分隔行
    body = [r for r in rows if not re.match(r"^\s*\|[\s:|\-]+\|\s*$", r)]
    if not body:
        return ""
    n_cols = max(len(r.strip().strip("|").split("|")) for r in body)
    html_rows = []
    for i, row in enumerate(body):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        cells += [""] * (n_cols - len(cells))
        tag = "th" if i == 0 else "td"
        html_rows.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
    return "<table>" + "".join(html_rows) + "</table>"


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + h.escape("\n".join(buf)) + "</code></pre>")
            continue

        # 表格
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(parse_table(rows))
            continue

        # 空行
        if not stripped:
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        # 分割线
        if re.match(r"^-{3,}\s*$", stripped):
            out.append("<hr/>")
            i += 1
            continue

        # blockquote（合并连续行）→ 渲染为带缩进样式的普通段落，避免被引擎并入相邻标题
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            text = "<br/>".join(inline(b) for b in buf if b)
            out.append(f'<p style="color:#6C757D; margin-left:12pt;">{text}</p>')
            continue

        # 列表（同类型连续块，含两级嵌套）
        m_ul = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        m_ol = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if m_ul or m_ol:
            ordered = bool(m_ol)
            items = []  # (indent, text)
            pat = r"^(\s*)\d+\.\s+(.*)$" if ordered else r"^(\s*)[-*]\s+(.*)$"
            while i < len(lines):
                mm = re.match(pat, lines[i])
                if not mm:
                    # 嵌套子列表项（另一种类型或缩进项）
                    mm2 = re.match(r"^(\s{2,})[-*]\s+(.*)$", lines[i]) if ordered else re.match(r"^(\s{2,})\d+\.\s+(.*)$", lines[i])
                    if mm2:
                        items.append((1, mm2.group(2)))
                        i += 1
                        continue
                    break
                items.append((0 if len(mm.group(1)) < 2 else 1, mm.group(2)))
                i += 1
            tag = "ol" if ordered else "ul"
            lis = []
            for indent, text in items:
                if indent:
                    lis.append(f"<li class='sub'>{inline(text)}</li>")
                else:
                    lis.append(f"<li>{inline(text)}</li>")
            out.append(f"<{tag}>" + "".join(lis) + f"</{tag}>")
            continue

        # 普通段落（合并到行尾）
        out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    return "\n".join(out)


CSS = """
<style>
:root {
  --font-body: "Microsoft YaHei", "SimSun", sans-serif;
  --font-head: "Microsoft YaHei", "SimHei", sans-serif;
  --color-primary: #714B67;
  --color-text: #212529;
  --color-muted: #6C757D;
  --color-border: #CCCCCC;
  --color-code-bg: #F5F5F5;
}
body { font-family: var(--font-body); font-size: 11pt; color: var(--color-text); line-height: 1.6; }
h1 { font-family: var(--font-head); font-size: 22pt; color: var(--color-primary); border-bottom: 2px solid var(--color-primary); padding-bottom: 8px; }
h2 { font-family: var(--font-head); font-size: 17pt; color: var(--color-primary); margin-top: 24px; }
h3 { font-family: var(--font-head); font-size: 14pt; color: var(--color-text); margin-top: 18px; }
h4 { font-family: var(--font-head); font-size: 12pt; color: var(--color-text); margin-top: 14px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th { background-color: #EFE9ED; border: 1px solid var(--color-border); padding: 5px 8px; font-weight: bold; text-align: left; }
td { border: 1px solid var(--color-border); padding: 5px 8px; }
code { font-family: Consolas, monospace; background-color: var(--color-code-bg); }
pre { background-color: var(--color-code-bg); border: 1px solid var(--color-border); padding: 8px; font-size: 9.5pt; }
pre code { background-color: transparent; }
blockquote { border-left: 3px solid var(--color-primary); padding-left: 10px; color: var(--color-muted); margin: 8px 0; }
hr { border: none; border-top: 1px solid var(--color-border); margin: 16px 0; }
li { margin: 3px 0; }
li.sub { margin-left: 18pt; color: var(--color-text); }
strong { color: #000000; }
</style>
"""


def main():
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()
    body = md_to_html(md)
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"/><title>智财代账工作台项目书</title>{CSS}</head>
<body>
{body}
</body>
</html>"""
    with open(dst, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"OK -> {dst}")


if __name__ == "__main__":
    main()
