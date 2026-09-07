"""Convert Odoo rich HTML into the small HTML subset Telegram accepts.

Telegram's ``parse_mode=HTML`` supports only a handful of inline tags. Odoo
chatter and template bodies are full of <p>, <div>, <ul> and <table>; sending
those raw returns ``400 Bad Request: can't parse entities``.
"""

import re
from html import escape
from html.parser import HTMLParser

# Source tag -> canonical Telegram tag.
KEEP = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code",
    "pre": "pre",
    "blockquote": "blockquote",
    "tg-spoiler": "tg-spoiler",
    "a": "a",
}

# Tags that produce a line break when they close.
BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

MAX_LEN = 4096


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "li":
            self.parts.append("• ")
            return
        keep = KEEP.get(tag)
        if not keep:
            return
        if keep == "a":
            href = dict(attrs).get("href")
            if not href:
                return
            self.parts.append('<a href="%s">' % escape(href, quote=True))
        else:
            self.parts.append("<%s>" % keep)
        self.open_tags.append(keep)

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in BLOCK:
            self.parts.append("\n")
            return
        keep = KEEP.get(tag)
        if not keep or keep not in self.open_tags:
            return
        # Malformed nesting is resolved by closing greedily down to this tag.
        while self.open_tags:
            last = self.open_tags.pop()
            self.parts.append("</%s>" % last)
            if last == keep:
                break

    def handle_data(self, data):
        self.parts.append(escape(data, quote=False))

    def close_all(self):
        while self.open_tags:
            self.parts.append("</%s>" % self.open_tags.pop())


def _truncate(text, limit):
    """Cut ``text`` to ``limit`` characters without leaving a tag unclosed."""
    if len(text) <= limit:
        return text
    stack = []
    out = []
    used = 0
    for token in re.split(r"(<[^>]+>)", text):
        if not token:
            continue
        if token.startswith("<"):
            out.append(token)
            # Tags count towards the budget too, otherwise the result overruns.
            used += len(token)
            name = re.match(r"</?\s*([a-zA-Z0-9-]+)", token)
            if name:
                if token.startswith("</"):
                    if stack and stack[-1] == name.group(1):
                        stack.pop()
                else:
                    stack.append(name.group(1))
            continue
        closing_cost = sum(len(tag) + 3 for tag in stack) + 1
        room = limit - used - closing_cost
        if room <= 0:
            break
        if len(token) > room:
            out.append(token[:room])
            used += room
            break
        out.append(token)
        used += len(token)
    out.append("…")
    while stack:
        out.append("</%s>" % stack.pop())
    return "".join(out)


def html_to_telegram(html, limit=MAX_LEN):
    """Return ``html`` reduced to Telegram-safe markup, at most ``limit`` chars."""
    if not html:
        return ""
    parser = _Converter()
    parser.feed(html)
    parser.close()
    parser.close_all()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return _truncate(text, limit)
