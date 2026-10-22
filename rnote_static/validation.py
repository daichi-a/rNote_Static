"""Check links against the output inventory without accessing the network."""
from html.parser import HTMLParser
from posixpath import normpath
from urllib.parse import unquote, urljoin, urlsplit


class References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src", "poster", "data") and value:
                self.urls.add(value)


def check_links(pages, assets, config):
    available = set(pages) | set(assets)
    warnings = set()
    site = urlsplit(config["SITE_URL"])
    for page, text in pages.items():
        if not page.endswith((".html", ".htm")):
            continue
        parser = References()
        parser.feed(text)
        page_url = config["SITE_URL"] + page
        for value in parser.urls:
            if value.startswith("#"):
                continue
            parsed = urlsplit(urljoin(page_url, value))
            if parsed.scheme not in ("http", "https") or parsed.netloc != site.netloc:
                continue
            path = unquote(parsed.path)
            if not path.startswith(config.base):
                continue
            path = normpath(path[len(config.base):]).lstrip("/")
            if path == ".":
                path = ""
            if parsed.query:
                warnings.add(f"legacy query URL requires a hosting redirect: {value}")
            if path in available or any((path.rstrip("/") + "/" + index).lstrip("/") in available for index in ("index.htm", "index.html")):
                continue
            warnings.add(f"local link target absent from output: {value}")
    return warnings
