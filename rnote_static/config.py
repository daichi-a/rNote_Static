"""Read a narrowly scoped PHP configuration grammar, never evaluate PHP."""
import re
from pathlib import Path
from urllib.parse import urlsplit

from .common import BuildError, read_text


TOKEN = re.compile(r'''\s*(?:('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")|([A-Za-z_]\w*)|(-?\d+)|([.,();\[\]$=]))''', re.S)
COMMENTS = re.compile(r'''('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")|/\*.*?\*/|//[^\n]*|\#[^\n]*''', re.S)
DEFAULTS = {
    "SITE_TITLE": "rNote", "SITE_AUTHOR": "", "SITE_URL": "http://localhost/",
    "SITE_LANG": "ja", "SITE_CHARSET": "UTF-8", "DIR_DATA": "entries/",
    "NUM_ITEMS": 5, "FORTHBACKMODE": True, "USE_MOD_REWRITE": True,
    "DATETIME_FORMAT": "%m/%d %H:%M", "DATETIME_LOCALE": "ja_JP",
    "TAG_TITLE": "Title", "TAG_DATE": "Date", "TAG_TEXT": "Text",
    "TAG_DESCRIPTION": "Description", "EXT_DOCUMENT": ".xml", "EXT_ACCESS": ".htm",
    "FNAME_SKIN_EXT": ".skin", "FNAME_SKIN_BODY": "html_body.skin",
    "FNAME_SKIN_ITEM": "html_item.skin", "FNAME_RSS": "rss.rdf", "MAX_DESCRIPTION": 128,
    "FNAME_SKIN_RSS": "entries/rss_body.skin",
}
REQUIRED = set(DEFAULTS)


def uncomment(text):
    return COMMENTS.sub(lambda m: m[1] if m[1] else " " * (len(m[0]) - m[0].count("\n")) + "\n" * m[0].count("\n"), text)


def literal(token):
    quote, body = token[0], token[1:-1]
    def escape(match):
        char = match[1]
        if quote == "'":
            return char if char in ("'", "\\") else "\\" + char
        return {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}.get(char, "\\" + char)
    if quote == '"' and re.search(r"(?<!\\)\$", body):
        raise BuildError("PHP interpolation is unsupported in a static setting")
    return re.sub(r"\\(.)", escape, body, flags=re.S)


def expression(text, constants):
    pos, terms, expect_term = 0, [], True
    while pos < len(text.rstrip()):
        match = TOKEN.match(text, pos)
        if not match:
            raise BuildError("unsupported PHP configuration expression")
        pos = match.end()
        string, name, number, punct = match.groups()
        if expect_term:
            if string:
                terms.append(literal(string))
            elif number:
                terms.append(int(number))
            elif name and name.lower() in ("true", "false"):
                terms.append(name.lower() == "true")
            elif name in constants:
                terms.append(constants[name])
            else:
                raise BuildError("unsupported constant in configuration expression")
        elif punct != ".":
            raise BuildError("only literal concatenation is supported")
        expect_term = not expect_term
    if expect_term or not terms:
        raise BuildError("incomplete configuration expression")
    return terms[0] if len(terms) == 1 else "".join(str(t) for t in terms)


class Config(dict):
    def __init__(self, source, site_url=None):
        super().__init__(DEFAULTS)
        self.source = Path(source).resolve()
        self.categories = {"": "Home"}
        self.hidden = []
        path = self.source / "rnote_config.php"
        text = uncomment(read_text(path))
        # This site's public configuration precedes all executable request handlers.
        text = re.split(r"\bif\s*\(", text, maxsplit=1)[0]
        for match in re.finditer(r"\bdefine\s*\(\s*(['\"]?)(\w+)\1\s*,\s*((?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[^;'\"])*?)\)\s*;", text, re.S):
            name = match[2]
            if name not in REQUIRED:
                continue
            try:
                self[name] = expression(match[3], self)
            except BuildError as exc:
                raise BuildError(f"{path}:{text.count(chr(10), 0, match.start()) + 1}: {name}: {exc}") from exc
        for match in re.finditer(r"\$(category_name|nodisp_at_toplv)\s*\[\s*([^\]]*)\]\s*=\s*((?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[^;'\"])+);", text):
            value = expression(match[3], self)
            if match[1] == "category_name":
                self.categories[str(expression(match[2], self))] = str(value)
            else:
                self.hidden.append(str(value))
        if site_url:
            self["SITE_URL"] = site_url
        self["SITE_URL"] = self["SITE_URL"].rstrip("/") + "/"
        parsed = urlsplit(self["SITE_URL"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise BuildError("SITE_URL must be an absolute HTTP(S) directory URL")
        self.base = parsed.path
        self.data = (self.source / self["DIR_DATA"]).resolve()
        if not self.data.is_dir():
            raise BuildError(f"DIR_DATA is not a directory: {self.data}")
        if self["NUM_ITEMS"] < 1:
            raise BuildError("NUM_ITEMS must be positive")

    def category(self, name):
        return self.categories.get(name, name)
