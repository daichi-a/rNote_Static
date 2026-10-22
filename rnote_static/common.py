"""Small legacy text operations shared by the parser and renderer."""
import re
from datetime import datetime, timedelta, timezone


class BuildError(Exception):
    """An input cannot be safely or faithfully built."""


JST = timezone(timedelta(hours=9))
PHP = re.compile(r"<\?(?!xml\b)|<\s*script\b[^>]*\blanguage\s*=\s*[\"']?php\b|<%\s*(?![=$]|goto\b|label\b)", re.I)


def read_text(path, encoding="utf-8"):
    try:
        return path.read_text(encoding=encoding).lstrip("\ufeff")
    except (OSError, UnicodeError, LookupError) as exc:
        raise BuildError(f"{path}: cannot read input ({exc})") from exc


def reject_php(text, source):
    match = PHP.search(text)
    if match:
        line = text.count("\n", 0, match.start()) + 1
        raise BuildError(f"{source}:{line}: executable PHP syntax is forbidden; no PHP was executed")


def strip_tags(text):
    return re.sub(r"<!--.*?-->|<[^>]*>", "", text, flags=re.S)


def xml_tag(name, text):
    # rnote.php:get_XMLTag is deliberately greedy and does not parse XML.
    match = re.search(r"<" + re.escape(name) + r".*?>\s*(.*)\s*</" + re.escape(name) + r">", text, re.S)
    return match[1] if match else ""


def split_path(path):
    if re.fullmatch(r"[^.]*[^/]", path):
        path += "/"
    match = re.match(r"(^.*/|^)(.*?)$", path, re.S)
    return (match[1], match[2]) if match else ("", "")


def ext_change(path, suffix):
    return re.sub(r"\.[^/.]*$", "", path) + suffix


def truth(value, default=False):
    if value is None or value == "":
        return default
    return value in ("on", "true", "yes", "1", 1, True)


def php_int(value):
    """PHP 4 numeric-prefix conversion (important for malformed skin options)."""
    match = re.match(r"\s*([+-]?\d+)", str(value))
    return int(match[1]) if match else 0


def prefix(pattern, value):
    try:
        return re.search("^" + pattern, value) is not None
    except re.error as exc:
        raise BuildError(f"invalid legacy prefix expression {pattern!r}: {exc}") from exc


def parse_date(text, fallback):
    if not text:
        return datetime.fromtimestamp(fallback, JST)
    parts = [int(x) for x in re.findall(r"\d+", text)[:6]]
    defaults = [1970, 1, 1, 0, 0, 0]
    parts += defaults[len(parts):]
    y, m, d, hh, mm, ss = parts
    if m > 12 or d > 31 or hh > 24 or mm > 60 or ss > 60:
        return datetime.fromtimestamp(0, JST)
    offset = re.search(r"([+-])(\d+):(\d+)$", text)
    # PHP passes components to mktime; normalize rather than rejecting 24:00.
    total_months = y * 12 + (m or 1) - 1
    base = datetime(total_months // 12, total_months % 12 + 1, 1, tzinfo=JST)
    delta = timedelta(days=(d or 1) - 1, hours=hh, minutes=mm, seconds=ss)
    if offset:
        delta -= (1 if offset[1] == "+" else -1) * timedelta(hours=int(offset[2]), minutes=int(offset[3]))
    return base + delta


def date_string(date, options, config):
    fmt = options.get("fmt", config["DATETIME_FORMAT"])
    loc = options.get("locale", config["DATETIME_LOCALE"])
    # Avoid the process-global OS locale: Windows need not have ja_JP installed.
    if loc.startswith("ja"):
        fmt = fmt.replace("%a", "月火水木金土日"[date.weekday()])
    else:
        fmt = fmt.replace("%a", ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[date.weekday()])
    fmt = fmt.replace("%z", "+09:00")
    return date.strftime(fmt)
