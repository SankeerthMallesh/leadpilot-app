"""Tiny, safe markdown subset for AI replies: paragraphs, bullets, numbered lists, **bold**, `code`.

All input is HTML-escaped first, so model output can never inject markup.
"""
import html
import re

from markupsafe import Markup

_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_BULLET = re.compile(r"^\s*[-*] +")
_NUMBER = re.compile(r"^\s*\d+[.)] +")


def _inline(text: str) -> str:
    text = _CODE.sub(r'<code class="rounded bg-black/10 px-1 text-[0.85em]">\1</code>', text)
    return _BOLD.sub(r"<strong>\1</strong>", text)


def _items(lines: list[str], marker: re.Pattern[str]) -> str:
    return "".join(f"<li>{_inline(marker.sub('', line, count=1))}</li>" for line in lines)


def render(text: str) -> Markup:
    """Convert a markdown subset to safe HTML."""
    escaped = html.escape((text or "").strip(), quote=True)
    out: list[str] = []
    for block in re.split(r"\n{2,}", escaped):
        lines = block.split("\n")
        if all(_BULLET.match(line) for line in lines):
            out.append(f'<ul class="list-disc space-y-1 pl-5">{_items(lines, _BULLET)}</ul>')
        elif all(_NUMBER.match(line) for line in lines):
            out.append(f'<ol class="list-decimal space-y-1 pl-5">{_items(lines, _NUMBER)}</ol>')
        else:
            out.append("<p>" + "<br>".join(_inline(line) for line in lines) + "</p>")
    return Markup('<div class="space-y-2">' + "".join(out) + "</div>")
