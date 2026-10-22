"""Map legacy page state to actual static files."""
import re
from urllib.parse import quote, urlsplit

from .common import BuildError


class URLs:
    def __init__(self, config, index=None):
        self.config = config
        self.directory_indexes = {}
        self.index_articles = set()
        if index is not None:
            for directory in index.dirs:
                self.directory_indexes[directory] = "index.htm"
                if directory + "index" + config["EXT_DOCUMENT"] in index.entries:
                    self.index_articles.add(directory)

    def relative(self, url="", date="", page=0):
        url = url.lstrip("/").replace(self.config["EXT_DOCUMENT"], self.config["EXT_ACCESS"])
        if "\\" in url or any(p in (".", "..") for p in url.split("/")) or urlsplit(url).scheme or "?" in url or "#" in url:
            raise BuildError(f"invalid internal URL: {url!r}")
        if date:
            if not re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", date):
                raise BuildError(f"invalid archive date: {date!r}")
            url = url.rstrip("/") + "/_date/" + date + "/"
            url = url.lstrip("/")
        if page:
            url = url.rstrip("/") + f"/_page/{page + 1}/"
            url = url.lstrip("/")
        return url

    def link(self, url="", date="", page=0, full=False):
        path = quote(self.relative(url, date, page), safe="/-._~")
        return (self.config["SITE_URL"] if full else self.config.base) + path

    def output(self, context):
        path = self.relative(context.url, context.date, context.page)
        return path + self.directory_indexes.get(path, "index.htm") if not path or path.endswith("/") else path

    def rss(self):
        return self.config["SITE_URL"] + self.config["FNAME_RSS"]


def absolute_assets(text, base):
    # ChangeFullUrl in rnote.php only visits a/img/link, double-quoted attrs.
    def tag(match):
        def attr(m):
            value = m[2]
            if value.startswith(("http", "ftp", "mailto", "/")):
                return m[0]
            return m[1] + '="' + base + value + '"'
        return re.sub(r'(href|src|url)="([^"]*)"', attr, match[0], flags=re.S)
    return re.sub(r'<(?:a|img|link)\b[^>]*>', tag, text, flags=re.S)
