"""Port the relevant SelectFileList and forth/back selection semantics."""
from dataclasses import dataclass

from .common import BuildError, ext_change, prefix, split_path


@dataclass(frozen=True)
class Context:
    url: str = ""
    date: str = ""
    page: int = 0
    mode: str = ""


@dataclass
class Selection:
    files: list
    directory: str
    page: int
    num: int
    single: bool
    date: str
    sort: str


def select(index, context, num, sort="dr", url=None, date=None, page=None):
    c = index.config
    url = (context.url if url is None else url).removeprefix("/")
    date = (context.date if date is None else date).removeprefix("-")
    page = context.page if page is None else page
    directory, filename = split_path(url)
    names = list(index.ordered)
    if sort == "df":
        names.reverse()
    elif sort in ("ff", "fr"):
        names.sort(reverse=sort == "fr")
    elif sort not in ("dr", ""):
        raise BuildError(f"unsupported static sort: {sort}")
    if num < 1 or page < 0:
        raise BuildError("site_items num must be positive and page nonnegative")
    if filename:
        scope = directory.split("/")[0] if c["FORTHBACKMODE"] else ""
        names = [n for n in names if prefix(scope, n)]
        name = ext_change(url, c["EXT_DOCUMENT"])
        if name not in names:
            raise BuildError(f"article referenced by skin does not exist: {url}")
        return Selection(names, directory, names.index(name), 1, True, date, sort)
    names = [n for n in names if prefix(directory, n)
             and (directory or index.visible(n))
             and (not date or prefix(context.date, index.entries[n].date.strftime("%Y-%m-%d")))]
    # The context.date reference above is intentional: legacy SelectFileList uses $d,
    # not its $date parameter, for the actual prefix test.
    return Selection(names, directory, page, num, num == 1, date, sort)
