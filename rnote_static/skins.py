"""Parse rNote macros; these delimiters are not PHP execution."""
import re

from .common import BuildError, prefix, read_text, reject_php, split_path


COMMENT = re.compile(r"<!---.*?--->\n?", re.S)
TAG = re.compile(r"<%=\$(.+?)%>", re.S)


def options(raw):
    # Mirror SkinTagChk: strip literal newlines/tabs, decode escapes, protect
    # escaped punctuation and quoted spaces/equals, then split on spaces.
    raw = re.sub(r"[\t\r\n\x07]", "", raw).replace("\\n", "\n")
    raw = re.sub(r"\\(.)", lambda m: "\x07" + f"{ord(m[1]):02x}", raw)
    raw = re.sub(r'"([^"]*)"', lambda m: m[1].replace(" ", "\x0720").replace("=", "\x073D"), raw)
    result = {}
    for token in raw.split(" "):
        key, _, value = token.partition("=")
        if key:
            result[key] = re.sub(r"\x07(.{2})", lambda m: chr(int(m[1], 16)), value)
    return result


def find_tag(text, name):
    match = re.search(r"<%=\$" + re.escape(name) + r"\s*(.*?)%>", text, re.S)
    return (match, options(match[1])) if match else (None, {})


def replace_tags(text, name, function):
    # str_replace replaces every identical occurrence as the original does.
    for _ in range(10000):
        match, opt = find_tag(text, name)
        if not match:
            return text
        replacement = function(opt)
        new = text.replace(match[0], replacement)
        if new == text:
            raise BuildError(f"skin expansion did not progress: {name}")
        text = new
    raise BuildError(f"skin expansion limit: {name}")


class Skins:
    def __init__(self, config, index):
        self.config, self.index = config, index
        self.cache = {}
        self.active = []

    def path(self, name):
        path = (self.config.source / name).resolve()
        if not path.is_relative_to(self.config.source) and not path.is_relative_to(self.config.data):
            raise BuildError(f"skin path leaves source tree: {name}")
        return path

    def load(self, path):
        if path is None:
            raise BuildError("no applicable skin in category ancestry")
        path = path.resolve()
        if path not in self.cache:
            text = read_text(path, self.config["SITE_CHARSET"])
            self.index.remember(path)
            # Keep line positions in the PHP diagnostic even inside includes.
            checked = COMMENT.sub(lambda m: "\n" * m[0].count("\n"), text)
            reject_php(checked, path)
            for match in TAG.finditer(text):
                if "<%=$" not in match[0][4:]:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                self.index.warnings.add(f"{path}:{line}: malformed skin delimiter; interpreted using rnote.php SkinTagChk, not repaired")
            self.cache[path] = text
        return self.cache[path]

    def includes(self, text, depth=0):
        if depth > 50:
            raise BuildError("skin include depth exceeded (possible include cycle)")
        def include(opt):
            if "url" not in opt:
                return ""
            path = self.path(opt["url"])
            if path in self.active:
                raise BuildError(f"skin include cycle: {path}")
            self.active.append(path)
            try:
                return self.includes(self.load(path), depth + 1)
            finally:
                self.active.pop()
        return replace_tags(text, "include", include)

    def macros(self, text, context, entry=None):
        text = COMMENT.sub("", text)
        text = re.sub(r'<IsCategory\s+dir="(.*?)".*?>(.*?)</IsCategory>', r'<if category="\1">\2</if>', text, flags=re.S)
        text = re.sub(r'<ifdef\s+tag="(.*?)".*?>(.*?)</ifdef>', r'<if def_tag="\1">\2</if>', text, flags=re.S)
        text = re.sub(r'<ifndef\s+tag="(.*?)".*?>(.*?)</ifndef>', r'<if !def_tag="\1">\2</if>', text, flags=re.S)

        def condition(key, value):
            negate = key.startswith("!")
            key = key.lstrip("!")
            valid = False
            if key == "category":
                valid = prefix(value, context.url)
            elif key == "flag":
                valid = {"bHome": not context.url and not context.date,
                         "bSingle": bool(split_path(context.url)[1]),
                         "bCellphone": False}.get(value, False)
            elif key == "mode":
                valid = context.mode == value
            elif key == "def_tag" and entry is not None:
                valid = re.search(r"<" + re.escape(value) + r".*?>", entry.raw) is not None
            return not valid if negate else valid

        def block(fragment):
            while True:
                start = re.search(r"<if .*?>", fragment, re.S)
                if not start:
                    return fragment
                depth, end, close_start = 1, None, None
                for token in re.finditer(r"<if .*?>|</if\s*?>", fragment[start.end():], re.S):
                    depth += -1 if token[0].startswith("</") else 1
                    if depth == 0:
                        close_start = start.end() + token.start()
                        end = start.end() + token.end()
                        break
                if end is None:
                    raise BuildError("unclosed <if> in skin")
                opt = re.match(r'<if\s+(\S+)="(.*?)".*?>', start[0], re.S)
                if not opt:
                    raise BuildError("invalid <if> condition in skin")
                replacement = block(fragment[start.end():close_start]) if condition(opt[1], opt[2]) else ""
                fragment = fragment[:start.start()] + replacement + fragment[end:]
        text = block(text)
        while True:
            goto = re.search(r'<%goto\s+"(.*?)".*?%>', text, re.S)
            if not goto:
                break
            labels = list(re.finditer(r'<%label\s+"' + re.escape(goto[1]) + r'".*?%>', text[goto.end():], re.S))
            if labels:
                text = text[:goto.start()] + text[goto.end() + labels[-1].end():]
            else:
                text = text[:goto.start()] + text[goto.end():]
        text = re.sub(r"<%(?:goto|label).*?%>", "", text, flags=re.S)
        text = re.sub(r"\n\t*", "\n", text)
        return re.sub(r"\n+", "\n", text)
