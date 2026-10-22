"""Render the static presentation subset of rnote.php."""
import html
import re

from .common import (BuildError, date_string, ext_change, prefix, read_text,
                     reject_php, split_path, strip_tags, truth, xml_tag, php_int)
from .selection import Context, select
from .skins import TAG, options, replace_tags
from .config import uncomment
from .urls import absolute_assets


class Renderer:
    def __init__(self, config, index, skins, urls):
        self.c, self.index, self.skins, self.urls = config, index, skins, urls
        self.requests = set()
        self.item_cache = {}
        self.plugin_settings = None

    def entry_buffer(self, entry):
        text = re.sub(r"<%=.*?%>", "", entry.raw, flags=re.S)
        for key, base in (("site_link_full", self.c["SITE_URL"]), ("site_link", self.c.base)):
            marker = "\x07ESCAPED_LINK\x07"
            text = text.replace("$$" + key + "/", marker)
            text = text.replace("$" + key + "/", base)
            text = text.replace(marker, "$" + key + "/")
        return text

    def description(self, text, length):
        value = xml_tag(self.c["TAG_DESCRIPTION"], text) or xml_tag(self.c["TAG_TEXT"], text)
        value = re.sub(r"[\t\n\v\f\r]", "", strip_tags(value)).replace("　", "")
        for old, new in (("&amp;", "&"), ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
            value = value.replace(old, new)
        if len(value) > length:
            value = value[:length] + "..."
        return html.escape(value, quote=False).replace('"', "&quot;")

    def item(self, name, skin, context):
        entry = self.index.entries[name]
        path = skin or self.index.dirs[entry.directory].item
        # Conditions use the outer request (not the article embedded by site_items).
        key = (name, path, context)
        if key in self.item_cache:
            return self.item_cache[key]
        text = self.skins.load(path)
        # Removed online features: never render WriteBack includes or their forms.
        text = replace_tags(text, "WriteBack", lambda opt: "")
        text = self.skins.macros(text, context, entry)
        if not text.strip():
            return ""
        text = replace_tags(text, "Url", lambda o: self.urls.link(name, full=truth(o.get("fullpath"))))
        text = replace_tags(text, self.c["TAG_DATE"], lambda o: date_string(entry.date, o, self.c))
        text = replace_tags(text, self.c["TAG_TITLE"], lambda o: entry.title)
        category = "/".join(self.c.category(p) for p in entry.directory.split("/") if p) or self.c.category("")
        text = replace_tags(text, "Category", lambda o: category)
        buf = self.entry_buffer(entry)
        text = replace_tags(text, self.c["TAG_DESCRIPTION"], lambda o: self.description(buf, php_int(o.get("length", self.c["MAX_DESCRIPTION"]))))
        for tag in ("NumWB", "NumTB", "NumRF", "WB_Data", "TB_Data", "Ref_Data", "bbs_delete_id"):
            text = replace_tags(text, tag, lambda o: "")
        # Protect missing entry tags until the outer site replacements run.
        def other(match):
            name, _, tail = match[1].partition(" ")
            opt = options(tail)
            value = xml_tag(name, buf)
            if not value:
                return "\x07" + match[0][2:]
            if truth(opt.get("autolink")):
                value = re.sub(r"(https?|ftp|news)(://[\w+$;?.%,!#~*/:@&=_-]+)", r'<a href="\1\2" target="_blank">\1\2</a>', value, flags=re.ASCII)
            if truth(opt.get("targetblank")):
                value = re.sub(r"(<a\s.*?https?://.*?)>", r'\1 target="_blank">', value, flags=re.S)
            return value
        # Repeat like GetContentsEach, including tags inserted by entry fields.
        for _ in range(100):
            if not TAG.search(text):
                break
            text = TAG.sub(other, text)
        else:
            raise BuildError(f"recursive entry substitution: {name}")
        text = text.replace("\x07", "<%")
        reject_php(text, self.c.data / name)
        self.item_cache[key] = text
        return text

    def neighbors(self, fi):
        previous = following = ("", "")
        total = len(fi.files)
        if fi.single:
            if fi.page + 1 < total:
                name = fi.files[fi.page + 1]
                previous = (self.index.entries[name].title, self.urls.link(name))
            if fi.page > 0:
                name = fi.files[fi.page - 1]
                following = (self.index.entries[name].title, self.urls.link(name))
        else:
            for direction in (1, -1):
                page = fi.page + direction
                if 0 <= page and page * fi.num < total:
                    start = page * fi.num + 1
                    end = min(start + fi.num - 1, total)
                    title = str(start) + (f"-{end}" if end > start else "")
                    target = Context(fi.directory, fi.date, page)
                    self.requests.add(target)
                    pair = (title, self.urls.link(fi.directory, fi.date, page))
                    if direction == 1:
                        previous = pair
                    else:
                        following = pair
        return (following, previous) if fi.sort in ("ff", "df") else (previous, following)

    def breadcrumbs(self, context):
        category = f'<a href="{self.urls.link()}">{self.c.category("")}</a>'
        directory, _ = split_path(context.url)
        path = ""
        for part in directory.split("/"):
            if part:
                path += part + "/"
                category += f'/<a href="{self.urls.link(path)}">{self.c.category(part)}</a>'
        return category

    def navigation(self, fi, opt, context):
        if fi is None:
            return ""
        mode = opt.get("mode", "")
        total = len(fi.files)
        previous, following = self.neighbors(fi)
        def link(pair, label=None, attrs=""):
            title, url = pair
            return f'<a href="{url}"{attrs}>{title if label is None else label}</a>' if url else ""
        if mode == "link":
            result = f'<link rel="top" href="{self.urls.link()}" />\n'
            if total > fi.num:
                for relation, pair in (("prev", previous), ("next", following)):
                    if pair[1]:
                        result += f'<link rel="{relation}" href="{pair[1]}" title="{pair[0]}" />\n'
            return result
        if mode in ("prev", "next"):
            pair = previous if mode == "prev" else following
            if total <= fi.num or not pair[1]:
                return ""
            attrs = f' title="{pair[0]}"'
            for attr in ("id", "class"):
                if opt.get(attr):
                    attrs += f' {attr}="{opt[attr]}"'
            return link(pair, opt.get("str", "« " + pair[0] if mode == "prev" else pair[0] + " »"), attrs)
        category = self.breadcrumbs(context)
        if mode == "category":
            return category
        compact = mode == "compact"
        result = "" if compact else "<p>"
        directory, _ = split_path(context.url)
        if not fi.date or len(directory.split("/")) > 1:
            result += ("" if compact else "Category:") + category
        if fi.date:
            result += " " + ("" if compact else "Date:")
            date_parts = fi.date.split("-")
            for i, part in enumerate(date_parts):
                target_date = "-".join(date_parts[:i + 1])
                target = Context(fi.directory, target_date)
                self.requests.add(target)
                result += ("/" if i else "") + f'<a href="{self.urls.link(fi.directory, target_date)}">{self.c.category(part) if i < 2 else part}</a>'
        result += f"({total})<br>\n" if compact else f" (Total {total} items)</p>\n"
        if total > fi.num:
            result += "" if compact else "<p>"
            if fi.single:
                result += link(previous, opt.get("prev_str", "« " + previous[0])) + " | " + link(following, opt.get("next_str", following[0] + " »"))
            else:
                start = fi.page * fi.num + 1
                end = min(start + fi.num - 1, total)
                result += (link(previous, "« " + previous[0]) + " | ") if previous[1] else ""
                result += str(start) + (f"-{end}" if end > start else "")
                result += (" | " + link(following, following[0] + " »")) if following[1] else ""
            result += "" if compact else "</p>"
        return result

    def category_plugin(self, context, opt):
        # Read only the literal constructor settings; do not import/execute PHP.
        if self.plugin_settings is None:
            path = self.c.source / "plugins/navitools.php"
            text = uncomment(read_text(path))
            self.index.remember(path)
            positions = {m[2]: int(m[3]) for m in re.finditer(r"\$this->category_pos\[(['\"])(.*?)\1\]\s*=\s*(\d+)", text)}
            secrets = [m[2] for m in re.finditer(r"\$this->secret_category\[\]\s*=\s*(['\"])(.*?)\1", text)]
            self.plugin_settings = positions, secrets
        positions, secrets = self.plugin_settings
        directory, _ = split_path(context.url)
        parent = re.sub(r"[^/]+/$", "", directory)
        names = set()
        for name in self.index.dirs:
            if any(prefix(s, name) for s in secrets):
                continue
            if re.fullmatch(r"[^/]+/", name) or prefix(name, directory):
                names.add(name)
            else:
                for base in (directory, parent):
                    m = re.match("^" + re.escape(base) + r"([^/]*)/", name)
                    if m:
                        names.add(m[0])
                        break
        names = sorted(names, key=lambda n: (0 if not n else positions.get(n.split("/")[0], 9999), n))
        rows = []
        for name in names:
            parts = name.split("/")
            level = len(parts) - (1 if "no-home" in opt else 0)
            if level <= 0:
                continue
            label = self.c.category(parts[max(0, len(parts) - 2)]) or "Home"
            label = f'<a href="{self.urls.link(name)}">{label}</a>'
            if "no-count" not in opt:
                label += f" ({self.index.dirs[name].count})"
            rows.append((level, label))
        output, level = "", 0
        for new_level, label in rows:
            if new_level <= level:
                output += "</li>\n"
            while new_level > level:
                output += "<ul>\n"
                level += 1
            while new_level < level:
                output += "</ul></li>\n"
                level -= 1
            output += "  " * max(0, new_level - 1) + "<li>" + label
        while level > 0:
            level -= 1
            output += "</li>\n" + "  " * max(0, level - 1) + "</ul>"
        return output

    def page(self, context, body=None):
        directory, _ = split_path(context.url)
        if directory not in self.index.dirs:
            raise BuildError(f"missing category: {directory}")
        text = self.skins.includes(self.skins.load(body or self.index.dirs[directory].body))
        text = self.skins.macros(text, context)
        fi = None
        def items(opt):
            nonlocal fi
            explicit = "url" in opt or "date" in opt
            selected = select(self.index, context, php_int(opt.get("num", self.c["NUM_ITEMS"])), opt.get("sort", "dr"),
                              opt.get("url", "") if explicit else None,
                              opt.get("date", "") if explicit else None, 0 if explicit else None)
            if not explicit:
                fi = selected
            skin = self.skins.path(ext_change(opt["skin"], self.c["FNAME_SKIN_EXT"])) if "skin" in opt else None
            start, end = php_int(opt.get("start", 0)), php_int(opt.get("end", 0))
            loop_start = selected.page * selected.num
            loop_end = len(selected.files) if "end" in opt else min(loop_start + selected.num, len(selected.files))
            result, count = [], 1
            for name in selected.files[loop_start:loop_end]:
                value = self.item(name, skin, context)
                if value:
                    if start == 0 or count >= start:
                        result.append(value)
                    count += 1
                    if end and count > end:
                        break
            return "".join(result)
        text = replace_tags(text, "site_items", items)
        text = replace_tags(text, "navi_forthback", lambda o: self.navigation(fi, o, context))
        newest = next((self.index.entries[n].date for n in self.index.ordered if self.index.visible(n)), None)
        if newest is None and self.index.ordered:
            newest = self.index.entries[self.index.ordered[-1]].date
        text = replace_tags(text, "last_modified", lambda o: date_string(newest, o, self.c) if newest else "")
        def site_link(opt):
            if opt.get("skin") or opt.get("type"):
                raise BuildError("alternate skin/content-type site_link requires an explicit static output mapping")
            target = Context(opt.get("url", ""), opt.get("date", ""))
            if target.date:
                self.requests.add(target)
            return self.urls.link(target.url, target.date, full=truth(opt.get("fullpath")))
        text = replace_tags(text, "site_link", site_link)
        title = ""
        name = ext_change(context.url, self.c["EXT_DOCUMENT"])
        if context.url:
            title = self.index.entries[name].title if name in self.index.entries else "/".join(self.c.category(p) for p in context.url.split("/") if p)
        elif context.date:
            title = context.date
        values = {"site_base": self.c["SITE_URL"], "rss_url": self.urls.rss(),
                  "site_title": self.c["SITE_TITLE"], "site_entrytitle": " - " + title if title else "",
                  "site_url": self.c["SITE_URL"], "site_charset": self.c["SITE_CHARSET"],
                  "site_lang": self.c["SITE_LANG"], "site_author": self.c["SITE_AUTHOR"],
                  "rnote_version": "0.9.7.5", "rnote_url": "http://rinn.e-site.jp/rnote/"}
        for name, value in values.items():
            text = replace_tags(text, name, lambda o, v=value: v)
        def plugin(opt):
            if opt.get("name") == "navitools" and opt.get("func", "exec") == "category":
                return self.category_plugin(context, opt.get("opt", ""))
            raise BuildError(f"unsupported active plugin: {opt.get('name')} / {opt.get('func', 'exec')}")
        text = replace_tags(text, "plugin", plugin)
        text = replace_tags(text, "navi_category", lambda o: self.category_plugin(context, ""))
        for name in ("cookie_name", "cookie_url", "cookie_pass", "bbs_posturl"):
            text = replace_tags(text, name, lambda o: "")
        for match in TAG.finditer(text):
            self.index.warnings.add(f"unresolved skin tag removed as in rnote.php: {match[1].split()[0]}")
        text = re.sub(r"<%=.*?%>", "", text, flags=re.S)
        text = absolute_assets(text, self.c.base)
        reject_php(text, f"generated page {context.url or '/'}")
        def remove_post_form(match):
            self.index.warnings.add(f"removed dynamic POST form in {context.url or '/'}")
            return ""
        text = re.sub(r"<form\b(?=[^>]*\bmethod\s*=\s*['\"]?post\b)[^>]*>.*?</form\s*>", remove_post_form, text, flags=re.I | re.S)
        if re.search(r"<form\b[^>]*\bmethod\s*=\s*['\"]?post\b", text, re.I):
            raise BuildError(f"unclosed dynamic POST form in {context.url or '/'}")
        return text
