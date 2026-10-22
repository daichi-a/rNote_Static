"""Turn generated site links into file://-friendly relative references."""
import html
import posixpath
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit

from .selection import Context
from .common import BuildError


URL_ATTRS = {"href", "src", "action", "poster", "data", "background", "cite", "longdesc"}
ATTR = re.compile(r'''(?P<space>\s+)(?P<name>[^\s=<>/]+)(?:\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+)))?''', re.S)
CSS_URL = re.compile(r'''url\(\s*(?:(['"])(.*?)\1|([^\s)]*))\s*\)''', re.I | re.S)


def decode_asset(data, default="utf-8"):
    """Respect an authored HTML/CSS encoding and re-encode to the same codec."""
    encoding = default
    hint = re.search(rb'''(?:charset\s*=\s*["']?|encoding\s*=\s*["']|@charset\s+["'])([A-Za-z0-9_.-]+)''', data[:8192], re.I)
    if hint:
        encoding = hint[1].decode("ascii")
    if encoding.lower().replace("-", "_") in {"shift_jis", "sjis", "ms_kanji", "windows_31j"}:
        encoding = "cp932"
    if data.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    try:
        return data.decode(encoding), encoding
    except (UnicodeError, LookupError) as exc:
        raise BuildError(f"cannot decode authored asset using {encoding}: {exc}") from exc


def legacy_context(value, config):
    """Recognize old query navigation without interpreting dynamic CMS modes."""
    parsed = urlsplit(html.unescape(value))
    site = urlsplit(config["SITE_URL"])
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc and parsed.netloc != site.netloc:
        return None
    query = parse_qs(parsed.query)
    if not query or set(query) - {"u", "d", "p"}:
        return None
    path = unquote(parsed.path)
    if path.startswith(config.base):
        path = path[len(config.base):]
    path = path.lstrip("/")
    if path.endswith("rnote.php"):
        path = query.get("u", [""])[0]
    elif "u" in query:
        path = query["u"][0]
    if path and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    try:
        page = int(query.get("p", ["0"])[0])
    except ValueError:
        return None
    if page < 0:
        return None
    return Context(path, query.get("d", [""])[0], page)


class LocalLinks:
    def __init__(self, config, urls, available):
        self.config, self.urls = config, urls
        self.available = set(available)
        self.site = urlsplit(config["SITE_URL"])

    def reference(self, value, page, site_relative=True):
        value = html.unescape(value)
        if not value or value.startswith("#"):
            return value
        parsed = urlsplit(value)
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            return value
        if parsed.netloc and parsed.netloc != self.site.netloc:
            return value
        state = legacy_context(value, self.config)
        if state is not None:
            target = self.urls.output(state)
            query = ""
        else:
            path = unquote(parsed.path)
            if parsed.netloc or path.startswith("/"):
                if path.startswith(self.config.base):
                    path = path[len(self.config.base):]
                target = path.lstrip("/")
            elif site_relative:
                target = path
            else:
                target = posixpath.join(posixpath.dirname(page), path)
            target = posixpath.normpath(target)
            if target == ".":
                target = ""
            if target == ".." or target.startswith("../"):
                return value
            directory_key = target.rstrip("/") + "/" if target else ""
            if directory_key in self.urls.directory_indexes:
                target = directory_key + self.urls.directory_indexes[directory_key]
            elif target not in self.available:
                directory = target.rstrip("/")
                candidates = [(directory + "/index.htm").lstrip("/"), (directory + "/index.html").lstrip("/")]
                if target.endswith("index.html"):
                    candidates.insert(0, target[:-4] + "htm")
                target = next((p for p in candidates if p in self.available), target)
            query = parsed.query
        relative = posixpath.relpath(target or "index.htm", posixpath.dirname(page) or ".")
        return urlunsplit(("", "", quote(relative, safe="/-._~"), query, parsed.fragment))

    def css(self, text, page, site_relative=False):
        def replace(match):
            value = match[2] if match[1] else match[3]
            replacement = self.reference(value, page, site_relative)
            return 'url("' + replacement.replace('"', "%22") + '")' if replacement != value else match[0]
        text = CSS_URL.sub(replace, text)
        return re.sub(r'''(@import\s+)(['"])(.*?)\2''',
                      lambda m: m[1] + m[2] + self.reference(m[3], page, site_relative) + m[2], text, flags=re.I)

    def html(self, text, page, site_relative=True):
        linker = self
        line_starts = [0]
        line_starts.extend(m.end() for m in re.finditer("\n", text))
        edits = []

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=False)
                self.style_start = None

            def handle_starttag(self, tag, attrs):
                start = line_starts[self.getpos()[0] - 1] + self.getpos()[1]
                raw = self.get_starttag_text()
                if tag == "base":
                    edits.append((start, start + len(raw), ""))
                    return
                def attr(match):
                    name = match["name"].lower()
                    value = next((match[k] for k in ("double", "single", "bare") if match[k] is not None), None)
                    if value is None:
                        return match[0]
                    if name in URL_ATTRS:
                        new = linker.reference(value, page, site_relative)
                    elif name == "srcset" and not value.lstrip().startswith("data:"):
                        parts = []
                        for candidate in value.split(","):
                            fields = candidate.strip().split()
                            if fields:
                                fields[0] = linker.reference(fields[0], page, site_relative)
                            parts.append(" ".join(fields))
                        new = ", ".join(parts)
                    elif name == "style":
                        new = linker.css(html.unescape(value), page, site_relative)
                    elif name == "content" and dict(attrs).get("http-equiv", "").lower() == "refresh":
                        new = re.sub(r"(?i)(url\s*=\s*)(.*)", lambda m: m[1] + linker.reference(m[2].strip("'\""), page, site_relative), html.unescape(value))
                    else:
                        return match[0]
                    if new == html.unescape(value):
                        return match[0]
                    return match["space"] + match["name"] + '="' + html.escape(new, quote=True) + '"'
                changed = ATTR.sub(attr, raw)
                if changed != raw:
                    edits.append((start, start + len(raw), changed))
                if tag == "style":
                    self.style_start = start + len(raw)

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

            def handle_endtag(self, tag):
                if tag == "style" and self.style_start is not None:
                    end = line_starts[self.getpos()[0] - 1] + self.getpos()[1]
                    original = text[self.style_start:end]
                    changed = linker.css(original, page, site_relative)
                    if changed != original:
                        edits.append((self.style_start, end, changed))
                    self.style_start = None

        parser = Parser()
        parser.feed(text)
        parser.close()
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        return text
