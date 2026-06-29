#!/usr/bin/env python3
"""Convert Markdown docs to HTML for browser review.
Ported from the solar-agent project's equivalent script.

Run on demand after editing any listed doc:
    python scripts/maintenance/generate_doc_html.py

Maintains:
- One HTML file per .md in docs/html/
- docs/html/index.html — clickable index of all listed docs

Per-doc HTML is self-contained (no external dependencies, print-friendly,
one-click copy buttons on all code blocks).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
HTML_DIR = DOCS_DIR / "html"

# Source list — keep in sync with README's doc index.
GROUPS = [
    ("Project", [
        "PRD.md",
        "Cases_2-5_Analysis.md",
        "backlog.md",
    ]),
]


# ─── Markdown → HTML renderer ─────────────────────────────────────────────

def render_markdown(md_text: str) -> str:
    try:
        import markdown as md_lib  # type: ignore
    except ImportError:
        return _fallback_render(md_text)
    extensions = ["fenced_code", "tables", "toc", "sane_lists", "attr_list"]
    return md_lib.markdown(_preprocess_md(md_text), extensions=extensions)


def _preprocess_md(text: str) -> str:
    """Insert a blank line before any list that immediately follows a
    non-list, non-blank line. Python-Markdown requires this (CommonMark spec)."""
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    in_code = False
    list_marker = re.compile(r"^\s*(?:[\-\*\+]\s|\d+\.\s)")
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        out.append(line)
        if in_code:
            continue
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if (
                line.strip()
                and list_marker.match(nxt)
                and not list_marker.match(line)
            ):
                out.append("")
    return "\n".join(out)


def _fallback_render(md_text: str) -> str:
    """Self-contained Markdown → HTML fallback renderer."""
    lines = md_text.splitlines()
    n = len(lines)
    out: list[str] = []
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            fence_indent = len(line) - len(line.lstrip())
            out.append("<pre><code>")
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                inner = lines[i]
                trim = 0
                while trim < fence_indent and trim < len(inner) and inner[trim] == " ":
                    trim += 1
                out.append(_escape(inner[trim:]))
                i += 1
            out.append("</code></pre>")
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if re.match(r"^---+\s*$|^\*\*\*+\s*$", stripped):
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if "|" in line and i + 1 < n and _is_table_separator(lines[i + 1]):
            tbl_html, consumed = _parse_table(lines, i)
            out.append(tbl_html)
            i += consumed
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                s = lines[i].lstrip()[1:]
                if s.startswith(" "):
                    s = s[1:]
                quote_lines.append(s)
                i += 1
            joined = " ".join(l for l in quote_lines if l.strip())
            out.append(f"<blockquote><p>{_inline(joined)}</p></blockquote>")
            continue

        list_match = re.match(r"^(\s*)([\-\*\+]|\d+\.)\s+(.*)$", line)
        if list_match:
            indent_pat = re.compile(r"^(\s*)([\-\*\+]|\d+\.)\s+(.*)$")
            ordered = list_match.group(2).endswith(".")
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>")
            while i < n:
                lm = indent_pat.match(lines[i])
                if not lm:
                    if not lines[i].strip():
                        if i + 1 < n and indent_pat.match(lines[i + 1]):
                            i += 1
                            continue
                    break
                item_text = lm.group(3)
                i += 1
                while i < n and lines[i].startswith("  ") and not indent_pat.match(lines[i]):
                    if lines[i].strip().startswith("```"):
                        break
                    item_text += " " + lines[i].strip()
                    i += 1
                out.append(f"<li>{_inline(item_text)}</li>")
            out.append(f"</{tag}>")
            continue

        para_lines: list[str] = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            nxt_stripped = nxt.strip()
            if not nxt_stripped:
                break
            if (nxt_stripped.startswith("```")
                    or nxt_stripped.startswith(">")
                    or nxt_stripped.startswith("#")
                    or re.match(r"^(\s*)([\-\*\+]|\d+\.)\s+", nxt)
                    or re.match(r"^---+\s*$|^\*\*\*+\s*$", nxt_stripped)
                    or ("|" in nxt and i + 1 < n and _is_table_separator(lines[i + 1]))):
                break
            para_lines.append(nxt)
            i += 1
        para_text = " ".join(l.strip() for l in para_lines)
        out.append(f"<p>{_inline(para_text)}</p>")
    return "\n".join(out)


def _is_table_separator(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|") and "|" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    if not cells:
        return False
    sep_re = re.compile(r"^:?-{2,}:?$")
    return all(sep_re.match(c) for c in cells)


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _parse_table(lines: list[str], start: int) -> tuple[str, int]:
    n = len(lines)
    header_cells = _split_table_row(lines[start])
    i = start + 2
    body_rows: list[list[str]] = []
    while i < n:
        s = lines[i].strip()
        if not s or "|" not in s:
            break
        body_rows.append(_split_table_row(lines[i]))
        i += 1
    thead = "".join(f"<th>{_inline(c)}</th>" for c in header_cells)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>"
        for row in body_rows
    )
    html = f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"
    return html, (i - start)


def _inline(text: str) -> str:
    code_spans: list[str] = []

    def _stash_code(m):
        code_spans.append(m.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"
    text = re.sub(r"`([^`\n]+)`", _stash_code, text)

    link_spans: list[tuple[str, str]] = []

    def _stash_link(m):
        link_spans.append((m.group(1), m.group(2)))
        return f"\x00LINK{len(link_spans) - 1}\x00"
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _stash_link, text)

    escaped_chars: list[str] = []

    def _stash_esc(m):
        escaped_chars.append(m.group(1))
        return f"\x00ESC{len(escaped_chars) - 1}\x00"
    text = re.sub(r"\\([\\\*_`\[\]\(\)#\-])", _stash_esc, text)

    text = _escape(text)

    text = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])",
                  r"<em>\1</em>", text)

    for idx, (label, url) in enumerate(link_spans):
        replacement = f'<a href="{_escape(url)}">{_escape(label)}</a>'
        text = text.replace(f"\x00LINK{idx}\x00", replacement)

    for idx, code in enumerate(code_spans):
        text = text.replace(
            f"\x00CODE{idx}\x00", f"<code>{_escape(code)}</code>"
        )

    for idx, ch in enumerate(escaped_chars):
        text = text.replace(f"\x00ESC{idx}\x00", _escape(ch))
    return text


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ─── Cross-doc link rewriter ──────────────────────────────────────────────

_LINK_RE = re.compile(r'(href|src)="([^"]*?\.md)(#[^"]*)?"')


def rewrite_cross_doc_links(html: str, source_md_filename: str) -> str:
    def _sub(m):
        attr = m.group(1)
        target = m.group(2)
        anchor = m.group(3) or ""
        bare = Path(target).name
        new_target = bare[:-3] + ".html" if bare.endswith(".md") else bare
        return f'{attr}="{new_target}{anchor}"'
    return _LINK_RE.sub(_sub, html)


# ─── Page template ────────────────────────────────────────────────────────

_PAGE_CSS = """
body {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 28px 80px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  line-height: 1.55;
  color: #1c2233;
  background: #ffffff;
}
h1, h2, h3, h4 { line-height: 1.25; margin-top: 1.6em; color: #1c2233; }
h1 { font-size: 28px; border-bottom: 2px solid #d0d4dc; padding-bottom: 8px; }
h2 { font-size: 22px; border-bottom: 1px solid #e4e7ec; padding-bottom: 4px; margin-top: 2em; }
h3 { font-size: 18px; }
h4 { font-size: 15px; color: #4a5568; }
p { margin: 0.8em 0; }
a { color: #1d4ed8; text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f4f5f7; padding: 1px 5px; border-radius: 3px; font-size: 0.92em;
  color: #1c2233; border: 1px solid #e4e7ec;
}
pre {
  background: #f7f8fa; color: #1c2233; padding: 12px 16px; border-radius: 6px;
  overflow-x: auto; font-size: 13px; line-height: 1.5;
  border: 1px solid #d0d4dc;
}
pre code { background: transparent; padding: 0; color: inherit; border: none; }
.copy-wrap { position: relative; margin: 1em 0; }
.copy-btn {
  position: absolute; top: 6px; right: 8px;
  background: #ffffff; color: #1c2233;
  border: 1px solid #374151; border-radius: 4px;
  font-family: inherit; font-size: 12px; font-weight: 600;
  padding: 4px 10px; cursor: pointer; opacity: 0.85;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
}
.copy-btn:hover { opacity: 1; background: #f0f4ff; }
.copy-btn.copied { background: #1d4ed8; color: #ffffff; border-color: #1d4ed8; }
.copy-btn.failed { background: #fee2e2; color: #7f1d1d; border-color: #7f1d1d; }
.copy-wrap pre { margin: 0; padding-right: 84px; }
@media print {
  .copy-btn { display: none; }
  .copy-wrap pre { padding-right: 16px; }
}
blockquote {
  margin: 1em 0; padding: 8px 16px; background: #eff6ff;
  border-left: 4px solid #1d4ed8; color: #1e3a5f;
}
table { border-collapse: collapse; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #d0d4dc; padding: 6px 10px; text-align: left; }
th { background: #eef0f4; font-weight: 700; color: #1c2233; }
tr:nth-child(even) td { background: #f7f8fa; }
ul, ol { padding-left: 1.6em; margin: 0.6em 0; }
li { margin: 0.2em 0; }
hr { border: none; border-top: 1px solid #d0d4dc; margin: 2em 0; }
.doc-header {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 12px; color: #6b7280; padding-bottom: 12px;
  border-bottom: 1px solid #e4e7ec; margin-bottom: 12px;
}
.doc-header a { color: #6b7280; }
.doc-header a:hover { color: #1d4ed8; }
@media print {
  body { padding: 12px 12px 60px; }
  .doc-header { display: none; }
  pre, code { background: #ffffff !important; border-color: #6b7280 !important; }
  th { background: #ffffff !important; border-color: #1c2233 !important; }
  tr:nth-child(even) td { background: #ffffff !important; }
  a { color: #1c2233; text-decoration: underline; }
}
"""

_COPY_BUTTON_JS = r"""
(function () {
  document.querySelectorAll('pre').forEach(function (pre) {
    if (pre.parentElement && pre.parentElement.classList.contains('copy-wrap')) return;
    var wrap = document.createElement('div');
    wrap.className = 'copy-wrap';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-btn';
    btn.textContent = 'Copy';
    btn.setAttribute('aria-label', 'Copy code to clipboard');
    btn.addEventListener('click', function () {
      var text = pre.innerText.replace(/^\s+|\s+$/g, '');
      var done = function () {
        btn.textContent = 'Copied';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 1500);
      };
      var fail = function () {
        btn.textContent = 'Select manually';
        btn.classList.add('failed');
        setTimeout(function () {
          btn.textContent = 'Copy';
          btn.classList.remove('failed');
        }, 2500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fail);
      } else {
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'absolute';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          var ok = document.execCommand('copy');
          document.body.removeChild(ta);
          ok ? done() : fail();
        } catch (e) { fail(); }
      }
    });
    wrap.appendChild(btn);
  });
})();
"""

_PAGE_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Back-End Simulation docs</title>
<style>{css}</style>
</head>
<body>
<div class="doc-header">
  <span><a href="index.html">← Index</a></span>
  <span>Generated from <code>{md_name}</code></span>
</div>
{body}
<script>{copy_js}</script>
</body></html>
"""


def render_doc(md_path: Path, out_path: Path) -> None:
    md_text = md_path.read_text()
    body = render_markdown(md_text)
    body = rewrite_cross_doc_links(body, md_path.name)
    title = _first_h1(md_text) or md_path.stem.replace("_", " ").title()
    html = _PAGE_HTML_TEMPLATE.format(
        title=_escape(title),
        css=_PAGE_CSS,
        md_name=md_path.name,
        body=body,
        copy_js=_COPY_BUTTON_JS,
    )
    out_path.write_text(html)


def _first_h1(md_text: str) -> str:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# ─── Index page ───────────────────────────────────────────────────────────

_INDEX_CSS = _PAGE_CSS + """
.index-table { font-size: 14px; }
.index-table td.path { font-family: ui-monospace, monospace; font-size: 13px; }
.index-table td.html-col a { font-weight: 700; }
.index-table td.html-col { width: 90px; text-align: center; }
.missing { color: #9ca3af; font-style: italic; }
"""

_INDEX_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Back-End Simulation docs index</title>
<style>{css}</style>
</head>
<body>
<h1>Back-End Simulation documentation index</h1>
<p>Markdown source lives at <code>docs/*.md</code>. HTML mirrors render for easier reading.
Re-generate after edits with <code>python scripts/maintenance/generate_doc_html.py</code>.</p>
<p>Last generated: {generated_at}</p>
{tables}
</body></html>
"""


def render_index(groups: list[tuple[str, list[str]]]) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tables = []
    for group_name, files in groups:
        rows = []
        for fname in files:
            md_path = DOCS_DIR / fname
            html_name = fname[:-3] + ".html"
            html_path = HTML_DIR / html_name
            md_exists = md_path.exists()
            html_exists = html_path.exists()
            md_link = (
                f'<a href="../{fname}">{fname}</a>'
                if md_exists else f'<span class="missing">{fname}</span>'
            )
            html_link = (
                f'<a href="{html_name}">View HTML</a>'
                if html_exists
                else '<span class="missing">—</span>'
            )
            title = ""
            if md_exists:
                try:
                    title = _first_h1(md_path.read_text())
                except Exception:
                    pass
            rows.append(
                f"<tr><td class='path'>{md_link}</td>"
                f"<td>{_escape(title)}</td>"
                f"<td class='html-col'>{html_link}</td></tr>"
            )
        tables.append(
            f"<h2>{_escape(group_name)}</h2>"
            f'<table class="index-table">'
            f"<thead><tr><th>Markdown source</th><th>Title</th><th>HTML</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    return _INDEX_TEMPLATE.format(
        css=_INDEX_CSS,
        generated_at=datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M %Z"),
        tables="\n".join(tables),
    )


# ─── QA check ─────────────────────────────────────────────────────────────

def _strip_pre_blocks(html: str) -> str:
    stripped = re.sub(r"<pre>.*?</pre>", "PRE", html, flags=re.DOTALL)
    stripped = re.sub(r"<code>.*?</code>", "CODE", stripped, flags=re.DOTALL)
    return stripped


def qa_check_html(html: str, doc_name: str) -> list[str]:
    issues: list[str] = []
    scan = _strip_pre_blocks(html)

    if re.search(r"\*\*[^<\n]+?\*\*", scan):
        issues.append("leftover **bold** markdown — renderer didn't convert to <strong>")
    if re.search(r"(?:^|\n)\s*&gt;\s+\S", scan):
        issues.append("leftover blockquote markers (`>` rendered as `&gt;`)")
    if re.search(r"(?:^|\n)\s*\|[^|\n]+\|", scan):
        issues.append("leftover table row syntax — should become <table>")
    if "```" in scan:
        issues.append("leftover triple-backtick code fence — should become <pre><code>")
    if re.search(r"\[[^\]\n]+\]\([^)\n]+\)", scan):
        issues.append("leftover markdown link syntax `[text](url)`")
    if re.search(r"<p>\s*</p>", scan):
        issues.append("empty <p></p> paragraphs")
    if re.search(r"<t[dh]>\s*:?-{2,}:?\s*</t[dh]>", scan):
        issues.append("table separator row (`---`) leaked into a <td>/<th>")
    if re.search(r"<h[1-6]>\s*#+\s", scan):
        issues.append("ATX heading hashes leaked into rendered heading text")
    return issues


# ─── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    rendered = 0
    skipped = 0
    qa_failed: list[tuple[str, list[str]]] = []
    for _, files in GROUPS:
        for fname in files:
            md_path = DOCS_DIR / fname
            if not md_path.exists():
                print(f"  skip: {fname} (not present)")
                skipped += 1
                continue
            out_path = HTML_DIR / (fname[:-3] + ".html")
            render_doc(md_path, out_path)
            rendered += 1
            try:
                produced = out_path.read_text()
                issues = qa_check_html(produced, fname)
            except Exception as exc:
                issues = [f"qa-check raised: {exc}"]
            if issues:
                qa_failed.append((fname, issues))
                print(f"  QA FAIL: {fname}")
                for it in issues:
                    print(f"           - {it}")
            else:
                print(f"   ok:  {fname} → {out_path.relative_to(REPO_ROOT)}")
    index_html = render_index(GROUPS)
    index_path = HTML_DIR / "index.html"
    index_path.write_text(index_html)
    print(f"   ok:  index → {index_path.relative_to(REPO_ROOT)}")
    print(f"\nRendered {rendered} docs, skipped {skipped}.")
    if qa_failed:
        print(f"\nQA FAILED on {len(qa_failed)} doc(s):")
        for fname, issues in qa_failed:
            print(f"  - {fname}")
            for it in issues:
                print(f"      · {it}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
