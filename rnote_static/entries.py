"""Index the source hierarchy while preserving raw historical HTML."""
import hashlib
import re
from dataclasses import dataclass

from .common import BuildError, parse_date, prefix, read_text, strip_tags, xml_tag


@dataclass
class Entry:
    name: str
    raw: str
    title: str
    date: object
    directory: str


@dataclass
class Directory:
    body: object
    item: object
    count: int = 0


class Index:
    def __init__(self, config, excluded=()):
        self.config = config
        self.entries = {}
        self.dirs = {}
        self.excluded = tuple(x.strip("/") + "/" for x in excluded)
        self.fingerprints = {}
        self.warnings = set()
        self.walk(config.data, "", None, None)
        self.ordered = sorted(self.entries, key=lambda n: self.entries[n].date, reverse=True)
        self.dirs = dict(sorted(self.dirs.items()))

    def is_excluded(self, name):
        return any(name.startswith(x) for x in self.excluded)

    def remember(self, path):
        self.fingerprints[path] = hashlib.sha256(path.read_bytes()).digest()

    def walk(self, path, directory, body, item):
        c = self.config
        if (path / c["FNAME_SKIN_BODY"]).is_file():
            body = path / c["FNAME_SKIN_BODY"]
        if (path / c["FNAME_SKIN_ITEM"]).is_file():
            item = path / c["FNAME_SKIN_ITEM"]
        info = self.dirs[directory] = Directory(body, item)
        # PHP readdir order is retained for equal timestamps; no invented filename tie-break.
        for child in path.iterdir():
            if child.is_symlink():
                raise BuildError(f"source symlink is unsupported: {child}")
            name = directory + child.name
            if self.is_excluded(name + ("/" if child.is_dir() else "")):
                continue
            if child.is_dir() and not child.name.startswith("."):
                info.count += self.walk(child, name + "/", body, item)
            elif child.is_file() and child.name.endswith(c["EXT_DOCUMENT"]):
                raw = read_text(child, c["SITE_CHARSET"])
                self.remember(child)
                title = re.sub(r"[\t\n\v\f\r]", "", strip_tags(xml_tag(c["TAG_TITLE"], raw)))
                date_text = xml_tag(c["TAG_DATE"], raw)
                if not date_text:
                    self.warnings.add(f"{child}: missing Date; legacy filesystem ctime fallback is not portable")
                date = parse_date(date_text, child.stat().st_ctime)
                self.entries[name] = Entry(name, raw, title, date, directory)
                info.count += 1
        return info.count

    def visible(self, name):
        return not any(prefix(p, name) for p in self.config.hidden)

    def verify_unchanged(self):
        for path, digest in self.fingerprints.items():
            if hashlib.sha256(path.read_bytes()).digest() != digest:
                raise BuildError(f"source changed during build: {path}")
