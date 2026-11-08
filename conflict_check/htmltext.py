"""Readable article text from HTML, with the standard library only.

Used as a fallback when Tavily extract can't fetch an article. It keeps paragraph
and heading text, preferring the <article> element when there is one, and drops
scripts, navigation, footers and similar page furniture.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "figure", "button"}
BLOCK = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "col", "embed", "track"}


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_article = 0
        self.block: list[str] | None = None
        self.blocks: list[tuple[bool, str]] = []  # (inside <article>, text)
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        if tag in SKIP:
            self.skip += 1
        elif tag == "article":
            self.in_article += 1
        elif tag == "title":
            self._in_title = True
        elif tag in BLOCK and not self.skip:
            self._flush()
            self.block = []

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag in SKIP and self.skip:
            self.skip -= 1
        elif tag == "article" and self.in_article:
            self._flush()
            self.in_article -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self.block is not None and not self.skip:
            self.block.append(data)

    def _flush(self):
        if self.block is not None:
            text = re.sub(r"\s+", " ", "".join(self.block)).strip()
            if text:
                self.blocks.append((self.in_article > 0, text))
        self.block = None


def html_to_text(html: str) -> tuple[str, str]:
    """Returns (title, text). Paragraphs are separated by blank lines."""
    p = _Parser()
    p.feed(html)
    p.close()
    p._flush()
    blocks = [t for inside, t in p.blocks if inside] or [t for _, t in p.blocks]
    blocks = [b for b in blocks if len(b) > 30 or b.endswith((".", "”", '"', "?"))]  # drop menus and captions
    return re.sub(r"\s+", " ", p.title).strip(), "\n\n".join(blocks)
