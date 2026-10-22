"""Command-line orchestration, staged output, and source verification."""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from .common import BuildError, reject_php
from .config import Config
from .entries import Index
from .render import Renderer
from .selection import Context
from .skins import Skins
from .urls import URLs
from .validation import check_links


MARKER = ".rnote-static-output"
SERVER_SUFFIXES = {".php", ".php3", ".php4", ".php5", ".phtml", ".phar", ".cgi", ".pl", ".asp", ".aspx"}
PRIVATE_SUFFIXES = {".skin", ".log", ".cache", ".ini", ".bak"}
TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".svg", ".txt", ".xml", ".json", ".csv"}


def safe_output(source, output, data):
    output = output.resolve()
    protected = [source.resolve(), data.resolve()]
    protected += [p.resolve() for p in source.iterdir() if p.name != "public" and p.is_dir()]
    for path in protected:
        if path == output or path.is_relative_to(output):
            raise BuildError(f"output would replace source material: {output}")
    if output.is_relative_to(data) or any(output.is_relative_to(p) for p in protected[2:]):
        raise BuildError(f"output must not be inside source assets: {output}")
    if output.exists() and (output.is_symlink() or not output.is_dir() or not (output / MARKER).is_file()):
        raise BuildError(f"refusing to replace an unmanaged output directory: {output}")
    return output


def assets(config, index, roots):
    found = {}
    for root in roots:
        path = (config.source / root).resolve()
        if not path.is_relative_to(config.source) or path == config.source:
            raise BuildError(f"asset root must be a subdirectory of source: {root}")
        if not path.exists():
            index.warnings.add(f"asset directory absent: {root}")
            continue
        for child in path.rglob("*"):
            rel = child.relative_to(config.source)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if child.is_symlink():
                raise BuildError(f"asset symlink is unsupported: {child}")
            if not child.is_file():
                continue
            suffix = child.suffix.lower()
            if suffix in SERVER_SUFFIXES or suffix in PRIVATE_SUFFIXES:
                index.warnings.add(f"server/private asset excluded: {rel.as_posix()}")
                continue
            index.remember(child)
            if suffix in TEXT_SUFFIXES:
                # Decode only for PHP detection; bytes are copied without rewriting.
                reject_php(child.read_bytes().decode("utf-8", errors="replace"), child)
            found[rel.as_posix()] = child
    # Assets stored alongside entries retain their actual entries/... location.
    if config.data.is_relative_to(config.source):
        for child in config.data.rglob("*"):
            if not child.is_file() or child.suffix.lower() in PRIVATE_SUFFIXES | SERVER_SUFFIXES | {config["EXT_DOCUMENT"].lower()}:
                continue
            if any(part.startswith(".") for part in child.relative_to(config.data).parts):
                continue
            if index.is_excluded(child.relative_to(config.data).as_posix()):
                continue
            if child.is_symlink():
                raise BuildError(f"asset symlink is unsupported: {child}")
            index.remember(child)
            if child.suffix.lower() in TEXT_SUFFIXES:
                reject_php(child.read_bytes().decode("utf-8", errors="replace"), child)
            found[child.relative_to(config.source).as_posix()] = child
    return found


def build(args):
    config = Config(args.source, args.site_url)
    output = safe_output(config.source, Path(args.output).resolve() if args.output else config.source / "public", config.data)
    index = Index(config, args.exclude_category)
    for name in ("rnote_config.php", "rnote.php", "htaccess", ".htaccess"):
        path = config.source / name
        if path.is_file():
            index.remember(path)
    urls = URLs(config)
    renderer = Renderer(config, index, Skins(config, index), urls)
    requests = {Context(d) for d in index.dirs} | {Context(n.replace(config["EXT_DOCUMENT"], config["EXT_ACCESS"])) for n in index.entries}
    done, pages, failures = set(), {}, set()
    while requests:
        context = min(requests, key=lambda c: (c.url, c.date, c.page))
        requests.remove(context)
        if context in done:
            continue
        done.add(context)
        if len(done) > args.max_pages:
            raise BuildError(f"page limit exceeded ({args.max_pages}); check skin navigation")
        renderer.requests.clear()
        renderer.item_cache.clear()
        try:
            target = urls.output(context)
            if target in pages:
                raise BuildError(f"generated path collision: {target}")
            text = renderer.page(context)
            pages[target] = text
            requests.update(renderer.requests - done)
        except (BuildError, ValueError) as exc:
            failures.add(str(exc))
    try:
        rss_path = renderer.skins.path(config["FNAME_SKIN_RSS"])
        pages[config["FNAME_RSS"]] = renderer.page(Context(), rss_path)
    except (BuildError, ValueError) as exc:
        failures.add(str(exc))
    copied = {}
    try:
        copied = assets(config, index, args.asset_dir or ["style", "image", "data", "WebApps"])
    except BuildError as exc:
        failures.add(str(exc))
    if "index.html" in pages:
        if "index.htm" in pages:
            failures.add("top-page alias conflicts with article index.htm")
        else:
            pages["index.htm"] = pages["index.html"]
    for name in copied:
        if name in pages:
            failures.add(f"asset/page collision: {name}")
    index.warnings.update(check_links(pages, copied, config))
    index.verify_unchanged()
    report = {"builder_version": __version__, "entries": len(index.entries), "categories": len(index.dirs), "pages": len(pages),
              "assets": len(copied), "excluded_categories": list(index.excluded),
              "warnings": sorted(index.warnings), "errors": sorted(failures),
              "source_verified_unchanged": True, "written": False}
    if not failures and not args.check:
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".rnote-static-", dir=output.parent)).resolve()
        try:
            for name, text in pages.items():
                target = (staging / name).resolve()
                if not target.is_relative_to(staging):
                    raise BuildError(f"generated path escapes output: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding=config["SITE_CHARSET"], newline="\n") as stream:
                    stream.write(text)
            for name, source in copied.items():
                target = (staging / name).resolve()
                if not target.is_relative_to(staging):
                    raise BuildError(f"asset path escapes output: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            (staging / MARKER).write_text(f"Generated by rnote_static {__version__}; safe to rebuild.\n", encoding="utf-8")
            index.verify_unchanged()
            backup = None
            if output.exists():
                backup = Path(tempfile.mkdtemp(prefix=".rnote-static-old-", dir=output.parent)).resolve()
                backup.rmdir()
                output.rename(backup)
            try:
                staging.rename(output)
            except OSError:
                if backup:
                    backup.rename(output)
                raise
            if backup:
                if backup.parent != output.parent.resolve() or not (backup / MARKER).is_file():
                    raise BuildError(f"unexpected output backup path: {backup}")
                shutil.rmtree(backup)
            report["written"] = True
        finally:
            if staging.exists() and staging.parent == output.parent.resolve() and staging.name.startswith(".rnote-static-"):
                shutil.rmtree(staging)
    if args.report:
        report_path = Path(args.report).resolve()
        if report_path == config.source or report_path.is_relative_to(config.data) or report_path.is_relative_to(config.source) and report_path != output / "build-report.json":
            raise BuildError("report must be outside the legacy source tree")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for message in report["warnings"][:30]:
        print("WARNING:", message, file=sys.stderr)
    if len(report["warnings"]) > 30:
        print(f"WARNING: {len(report['warnings']) - 30} additional warnings; use --report to save all diagnostics", file=sys.stderr)
    for message in report["errors"]:
        print("ERROR:", message, file=sys.stderr)
    print(f"{report['entries']} entries, {report['categories']} categories, {report['pages']} pages, {report['assets']} assets; "
          + ("FAILED (output unchanged)" if failures else "checked" if args.check else f"written to {output}"))
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build rNote static pages with Python's standard library; never execute PHP.")
    parser.add_argument("--version", action="version", version="rnote_static " + __version__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1], help="legacy site root (default: beside entry script)")
    parser.add_argument("--output", help="output directory (default: SOURCE/public)")
    parser.add_argument("--site-url", help="override absolute deployment URL")
    parser.add_argument("--check", action="store_true", help="render/validate without writing public output")
    parser.add_argument("--report", help="write diagnostic JSON outside source tree")
    parser.add_argument("--exclude-category", action="append", default=[], help="explicit partial build: omit this category subtree (repeatable)")
    parser.add_argument("--asset-dir", action="append", help="asset directory relative to source (repeatable; replaces defaults)")
    parser.add_argument("--max-pages", type=int, default=50000, help="maximum generated page states")
    args = parser.parse_args(argv)
    try:
        return build(args)
    except (BuildError, OSError, ValueError, RecursionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
