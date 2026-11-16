"""Cronopios: a small, safe Markdown renderer for blog pieces in the client
portal, so the client reads an article (titles, bold, lists, tables, links)
instead of raw symbols. The text is HTML-escaped first; only the handful of
tags produced here can appear, and links must be http(s)."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")


def _inline(text):
    text = escape(text)
    text = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return _ITAL.sub(r"<em>\1</em>", text)


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


@register.filter
def cronopios_markdown(value):
    lines = (value or "").replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level = min(len(m.group(1)) + 1, 4)
            out.append(f'<h{level}>{_inline(m.group(2))}</h{level}>')
            i += 1
            continue
        if re.match(r"^-{3,}$", s):
            out.append('<hr>')
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and re.match(r"^\|?\s*:?-{2,}", lines[i + 1].strip()):
            head = _cells(s)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f'<th>{_inline(c)}</th>' for c in head)
            body = "".join(
                "<tr>" + "".join(f'<td>{_inline(c)}</td>' for c in r) + "</tr>"
                for r in rows
            )
            out.append(f'<div><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>')
            continue
        if re.match(r"^([-*]|\d+\.)\s+", s):
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < n and re.match(r"^([-*]|\d+\.)\s+", lines[i].strip()):
                items.append(re.sub(r"^([-*]|\d+\.)\s+", "", lines[i].strip()))
                i += 1
            tag = "ol" if ordered else "ul"
            lis = "".join(f'<li>{_inline(t)}</li>' for t in items)
            out.append(f'<{tag}>{lis}</{tag}>')
            continue
        para = []
        while i < n and lines[i].strip() and not re.match(r"^(#{1,4}\s|\||([-*]|\d+\.)\s|-{3,}$)", lines[i].strip()):
            para.append(_inline(lines[i].strip()))
            i += 1
        out.append('<p>' + "<br>".join(para) + "</p>")
    return mark_safe('<div class="cr-md">' + "\n".join(out) + "</div>")
