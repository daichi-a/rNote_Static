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


def check_links(pages, assets, config, managed_roots=()):
    """Validate only builder-owned targets; other site files are user-managed.

    Do not probe the source or deployment filesystem for unmanaged links.
    A .htm extension alone does not establish that rNote owns a target.
    """
    available = set(pages) | set(assets)
    roots = tuple(normpath(str(root)).strip("/") + "/" for root in managed_roots)
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
            known = path in available or any((path.rstrip("/") + "/" + index).lstrip("/") in available for index in ("index.htm", "index.html"))
            if not known and not any(path == root.rstrip("/") or path.startswith(root) for root in roots):
                continue
            if parsed.query:
                warnings.add(f"legacy query URL requires a hosting redirect: {value}")
            if known:
                continue
            warnings.add(f"local link target absent from output: {value}")
    return warnings
