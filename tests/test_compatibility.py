"""Synthetic regression fixtures; no original site material is redistributed."""
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rnote_static import __version__
from rnote_static.build import main, safe_output, private_asset
from rnote_static.common import BuildError, date_string, parse_date, reject_php, split_path, xml_tag
from rnote_static.config import Config, expression
from rnote_static.entries import Index
from rnote_static.render import Renderer
from rnote_static.selection import Context, select
from rnote_static.skins import Skins, find_tag, options
from rnote_static.urls import URLs, absolute_assets
from rnote_static.validation import check_links
from rnote_static.local_links import LocalLinks, legacy_context, decode_asset


CONFIG = """<?php
// public settings
define(SITE_TITLE, 'Example // title');
define(SITE_AUTHOR, 'Writer');
define(SITE_URL, 'https://example.test/blog/');
define(SITE_CHARSET, 'UTF-8');
define(DIR_DATA, 'entries/');
define(FNAME_SKIN_EXT, '.skin');
define(FNAME_SKIN_BODY, 'html_body'.FNAME_SKIN_EXT);
define(FNAME_SKIN_ITEM, 'html_item'.FNAME_SKIN_EXT);
define(FNAME_SKIN_RSS, DIR_DATA.'rss_body'.FNAME_SKIN_EXT);
define(NUM_ITEMS, 2);
$category_name[''] = 'Home';
$category_name['work'] = 'Works';
$nodisp_at_toplv[] = 'hidden';
if (true) { file_put_contents('MUST_NOT_EXIST', 'executed'); }
?>"""


class Compatibility(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.write("rnote_config.php", CONFIG)
        self.write("rnote.php", "<?php /* compatibility reference only */ ?>")
        self.write("entries/html_body.skin", '<html><%=$site_title%><%=$site_entrytitle%><%=$site_items%><%=$navi_forthback%><img src="image/a.png"></html>')
        self.write("entries/html_item.skin", '<h2><%=$Title%></h2><div><%=$Text%></div>')
        self.write("entries/rss_body.skin", '<?xml version="1.0"?><rss><%=$site_items url="" num="15" skin="entries/rss_item.skin"%></rss>')
        self.write("entries/rss_item.skin", '<item><%=$Url fullpath="1"%> <%=$Description%></item>')
        self.entry("work/a.xml", "Older", "2020-01-01T12:00:00", '<p>A &amp; B<br>raw</p>')
        self.entry("work/sub/b.xml", "Newer", "2021-01-02T12:00:00", "Second")
        self.entry("work/sub/c.xml", "Newest", "2022-01-03T12:00:00", "Third")
        self.entry("other/d.xml", "Other", "2023-01-04T12:00:00", "Fourth")
        self.entry("hidden/e.xml", "Hidden", "2024-01-05T12:00:00", "Secret")
        self.make_renderer()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def entry(self, name, title, date, body):
        self.write("entries/" + name, f'<rNote><Title>{title}</Title><Date>{date}</Date><Text>{body}</Text></rNote>')

    def make_renderer(self):
        self.config = Config(self.root)
        self.index = Index(self.config)
        self.skins = Skins(self.config, self.index)
        self.urls = URLs(self.config, self.index)
        self.renderer = Renderer(self.config, self.index, self.skins, self.urls)

    def test_configuration_literals_and_no_execution(self):
        self.assertEqual(self.config["SITE_TITLE"], "Example // title")
        self.assertEqual(self.config["FNAME_SKIN_RSS"], "entries/rss_body.skin")
        self.assertEqual(self.config.categories["work"], "Works")
        self.assertEqual(self.config.hidden, ["hidden"])
        self.assertFalse((self.root / "MUST_NOT_EXIST").exists())
        with self.assertRaises(BuildError):
            expression("system('anything')", {})

    def test_permissive_raw_markup(self):
        buf = self.index.entries["work/a.xml"].raw
        self.assertIn("<br>raw", xml_tag("Text", buf))
        self.assertIn("A &amp; B<br>raw", self.renderer.page(Context("work/a.htm")))

    def test_separate_body_item_inheritance_and_per_entry_skin(self):
        self.write("entries/work/html_body.skin", "WORK:<%=$site_items%>")
        self.write("entries/work/sub/html_item.skin", "SUB:<%=$Title%>")
        self.make_renderer()
        self.assertEqual(self.index.dirs["work/sub/"].body, self.root / "entries/work/html_body.skin")
        self.assertEqual(self.index.dirs["work/sub/"].item, self.root / "entries/work/sub/html_item.skin")
        page = self.renderer.page(Context("work/"))
        self.assertIn("WORK:SUB:NewestSUB:Newer", page)
        self.assertEqual(self.index.dirs["work/"].count, 3)

    def test_explicit_item_skin(self):
        self.write("entries/html_body.skin", '<%=$site_items url="work/a.htm" skin="entries/custom"%>')
        self.write("entries/custom.skin", "CUSTOM:<%=$Title%>")
        self.assertEqual(self.renderer.page(Context()), "CUSTOM:Older")

    def test_sort_and_top_exclusion(self):
        default = select(self.index, Context(), 2)
        self.assertEqual(default.files[0], "other/d.xml")
        self.assertNotIn("hidden/e.xml", default.files)
        self.assertIn("hidden/e.xml", select(self.index, Context("hidden/"), 2).files)
        self.assertEqual(select(self.index, Context("work/"), 2, "ff").files[0], "work/a.xml")
        self.assertEqual(select(self.index, Context("work/"), 2, "df").files[0], "work/a.xml")

    def test_single_navigation_uses_top_category(self):
        selected = select(self.index, Context("work/sub/b.htm"), 2)
        self.assertIn("work/a.xml", selected.files)
        self.assertNotIn("other/d.xml", selected.files)
        previous, following = self.renderer.neighbors(selected)
        self.assertEqual(previous[0], "Older")
        self.assertEqual(following[0], "Newest")

    def test_pagination_and_archive_real_paths(self):
        page = self.renderer.page(Context("work/"))
        self.assertIn('/blog/work/_page/2/', page)
        self.assertIn(Context("work/", "", 1), self.renderer.requests)
        self.assertEqual(self.urls.output(Context("work/", "2020-01", 1)), "work/_date/2020-01/_page/2/index.htm")
        self.assertEqual(self.urls.link("work/a.xml", full=True), "https://example.test/blog/work/a.htm")

    def test_legacy_explicit_date_bug_is_retained(self):
        result = select(self.index, Context("", "2021"), 2, date="2020", url="")
        self.assertEqual(result.files, ["work/sub/b.xml"])
        result = select(self.index, Context(), 2, date="2020", url="")
        self.assertEqual(len(result.files), 4)

    def test_malformed_delimiter_uses_next_closing_tag(self):
        match, opt = find_tag('<%=$site_items% sort="ff" num="1"><div><%=$navi_forthback%>', "site_items")
        self.assertTrue(match[0].endswith("navi_forthback%>"))
        self.assertEqual(opt["sort"], "ff")
        self.write("entries/html_body.skin", '<%=$site_items% sort="ff" num="1"><div><%=$navi_forthback%>END')
        page = self.renderer.page(Context("work/"))
        self.assertIn("Older", page)
        self.assertEqual(page, '<h2>Older</h2><div><p>A &amp; B<br>raw</p></div>END')
        self.assertTrue(self.index.warnings)

    def test_options_and_nested_conditions_and_goto(self):
        self.assertEqual(options('fmt="a b=1\\n\\\"quote\\\""'), {"fmt": 'a b=1\n"quote"'})
        text = '<!---deleted---><if category="work/"><if !flag="bCellphone">yes</if></if><if flag="bHome">home</if><%goto "end"%>skip<%label "end"%>tail'
        self.assertEqual(self.skins.macros(text, Context("work/a.htm")), "yestail")
        with self.assertRaises(BuildError):
            self.skins.macros('<if flag="bHome">bad', Context())

    def test_missing_entry_tag_is_removed_at_finalize(self):
        self.write("entries/html_item.skin", '<%=$Unknown%><%=$Title%>')
        page = self.renderer.page(Context("work/a.htm"))
        self.assertIn("Older", page)
        self.assertNotIn("<%=", page)

    def test_relative_asset_links_are_site_root_relative(self):
        result = absolute_assets('<a href="x.htm">x</a><img src="a.png"><link href="s.css"><script src="js.js"></script>', "/blog/")
        self.assertIn('href="/blog/x.htm"', result)
        self.assertIn('src="/blog/a.png"', result)
        self.assertIn('src="js.js"', result)  # PHP does not rewrite script.

    def test_php_detection_distinguishes_xml(self):
        reject_php('<?xml version="1.0"?>', "test")
        for code in ("<?php echo 1; ?>", "<?= 1 ?>", "<? echo 1 ?>"):
            with self.assertRaisesRegex(BuildError, "test:2"):
                reject_php("\n" + code, "test")
        self.write("entries/html_body.skin", "\n<? echo 1 ?>")
        with self.assertRaisesRegex(BuildError, "html_body.skin:2"):
            self.renderer.page(Context())

    def test_include_cycle_reports_error(self):
        self.write("entries/loop.skin", '<%=$include url="entries/loop.skin"%>')
        self.write("entries/html_body.skin", '<%=$include url="entries/loop.skin"%>')
        with self.assertRaisesRegex(BuildError, "cycle"):
            self.renderer.page(Context())

    def test_removed_post_form(self):
        self.write("entries/html_body.skin", '<p>Before</p><form method="post"><input name="Text"></form><p>After</p>')
        page = self.renderer.page(Context())
        self.assertEqual(page, '<p>Before</p><p>After</p>')
        self.assertTrue(any("POST form" in w for w in self.index.warnings))

    def test_static_credit_uses_builder_version_without_changing_article(self):
        skin = '<h4>Powered by</h4><div class="side"><a href="<%=$rnote_url%>"><img src="style/rnote-logo.gif"><br>Powered by rNote <%=$rnote_version%></a></div>'
        self.write("entries/credit.skin", skin)
        self.write("entries/html_body.skin", '<%=$site_items%><%=$include url="entries/credit.skin"%>')
        self.entry("work/credit.xml", "Credit", "2025-01-01", "Powered by rNote 0.9.7.5")
        self.make_renderer()
        page = self.renderer.page(Context("work/credit.htm"))
        self.assertIn(f'<h4>Powered by</h4><div class="side">\nrNote Static {__version__}\n</div>', page)
        self.assertNotIn("rnote-logo.gif", page)
        self.assertNotIn("http://rinn.e-site.jp/rnote/", page)
        self.assertIn('<div>Powered by rNote 0.9.7.5</div>', page)
        self.assertEqual((self.root / "entries/credit.skin").read_text(encoding="utf-8"), skin)

    def test_link_inventory_preserves_existing_broken_links_as_warnings(self):
        warnings = check_links({"work/a.htm": '<a href="/blog/work/">ok</a><img src="/blog/image/a.png"><a href="/blog/missing.htm">old</a>', "work/index.html": ""}, {"image/a.png": None}, self.config)
        self.assertEqual(warnings, {"local link target absent from output: /blog/missing.htm"})

    def test_category_plugin_literal_settings(self):
        self.write("plugins/navitools.php", "<?php $this->category_pos['work']=1; $this->secret_category[]='hidden'; ?>")
        page = self.renderer.category_plugin(Context("work/sub/"), "")
        self.assertIn('href="/blog/work/">Works</a> (3)', page)
        self.assertNotIn('href="/blog/hidden/"', page)
        self.assertIn('<ul>', page)
        page = self.renderer.category_plugin(Context("work/sub/"), "no-count,no-home")
        self.assertNotIn("(3)", page)
        self.assertNotIn('href="/blog/">Home', page)

    def test_source_and_output_guards(self):
        for output in (self.root, self.root.parent, self.root / "entries/public"):
            with self.assertRaises(BuildError):
                safe_output(self.root, output, self.config.data)
        unmanaged = self.root.parent / "unmanaged"
        unmanaged.mkdir()
        with self.assertRaises(BuildError):
            safe_output(self.root, unmanaged, self.config.data)
        self.index.remember(self.root / "rnote_config.php")
        self.write("rnote_config.php", "changed")
        with self.assertRaisesRegex(BuildError, "source changed"):
            self.index.verify_unchanged()

    def test_complete_build_rebuild_and_failure_preserves_output(self):
        output = self.root.parent / "public"
        before = {str(p): hashlib.sha256(p.read_bytes()).digest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 0)
        self.assertTrue((output / "work/a.htm").is_file())
        self.assertTrue((output / "work/_page/2/index.htm").is_file())
        self.assertTrue((output / "index.htm").is_file())
        self.assertFalse(list(output.rglob("*.html")))
        self.assertTrue((output / "rss.rdf").is_file())
        htaccess = (output / ".htaccess").read_text(encoding="utf-8")
        self.assertIn("DirectoryIndex index.htm\n", htaccess)
        self.assertNotIn("rnote.php", htaccess)
        self.assertNotIn("RewriteRule", htaccess)
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 0)
        after = {str(p): hashlib.sha256(p.read_bytes()).digest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        old = (output / "index.htm").read_bytes()
        self.write("entries/html_body.skin", "<?php forbidden ?>")
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 1)
        self.assertEqual((output / "index.htm").read_bytes(), old)

    def test_file_relative_links_cover_navigation_and_resources(self):
        available = {"index.htm", "work/index.htm", "work/a.htm", "style/a.css", "style/a.js", "image/a.png", "rss.rdf"}
        linker = LocalLinks(self.config, self.urls, available)
        page = linker.html('''<a href="/blog/">Home</a><a href="https://example.test/blog/work/">Works</a>
<a href="/blog/work/a.htm#section">Article</a><link href="style/a.css"><script src='/blog/style/a.js'></script>
<img src="/blog/image/a.png"><a href="https://outside.test/blog/">Outside</a><a href="#here">Anchor</a>''', "work/sub/b.htm")
        self.assertIn('href="../../index.htm"', page)
        self.assertIn('href="../index.htm"', page)
        self.assertIn('href="../a.htm#section"', page)
        self.assertIn('href="../../style/a.css"', page)
        self.assertIn('src="../../style/a.js"', page)
        self.assertIn('src="../../image/a.png"', page)
        self.assertIn('href="https://outside.test/blog/"', page)
        self.assertIn('href="#here"', page)

    def test_copied_manual_html_and_css_keep_their_own_relative_base(self):
        linker = LocalLinks(self.config, self.urls, {"WebApps/sample/index.html", "WebApps/shared.js", "image/a.png", "style/bg.png"})
        page = linker.html('<script src="../shared.js"></script><img src="/blog/image/a.png">', "WebApps/sample/index.html", site_relative=False)
        self.assertIn('src="../shared.js"', page)
        self.assertIn('src="../../image/a.png"', page)
        self.assertEqual(linker.css('a{background:url("/blog/image/a.png")}b{background:url(bg.png)}', "style/a.css"), 'a{background:url("../image/a.png")}b{background:url(bg.png)}')
        self.assertEqual(linker.reference("data:image/png;base64,abc", "a.htm"), "data:image/png;base64,abc")

    def test_relative_rewriter_does_not_edit_script_or_article_text(self):
        linker = LocalLinks(self.config, self.urls, {"index.htm"})
        raw = '''<script>const s='<a href="/blog/">';</script><p>/blog/ is a textual example.</p>'''
        self.assertEqual(linker.html(raw, "work/a.htm"), raw)

    def test_legacy_query_links_have_static_file_targets(self):
        target = "work/_date/2020/_page/2/index.htm"
        linker = LocalLinks(self.config, self.urls, {target})
        state = legacy_context("/blog/work/?d=2020&p=1", self.config)
        self.assertEqual(state, Context("work/", "2020", 1))
        self.assertEqual(linker.reference("/blog/work/?d=2020&amp;p=1#x", "work/sub/a.htm"), "../_date/2020/_page/2/index.htm#x")
        self.assertIsNone(legacy_context("https://outside.test/?p=1", self.config))
        self.assertIsNone(legacy_context("/blog/?m=wb_write", self.config))

    def test_historical_logs_are_not_copied_or_rendered(self):
        for name in ("entries/work/a.log", "entries/work/a_ref.txt", "entries/work/referer.txt", "style/comments/2020.txt", "data/old.ref"):
            self.write(name, "HISTORICAL_PRIVATE_MARKER")
            self.assertTrue(private_asset(name))
        self.write("image/a.png", "image-fixture")
        output = self.root.parent / "public"
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 0)
        self.assertFalse((output / "image/a.png").exists())
        for path in output.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"HISTORICAL_PRIVATE_MARKER", path.read_bytes())
                self.assertFalse(path.suffix in {".log", ".ref"})
        article = (output / "work/a.htm").read_text(encoding="utf-8")
        self.assertIn('src="../image/a.png"', article)
        self.assertIn('href="index.htm"', article)

    def test_only_style_assets_are_copied_by_default(self):
        for name in ("image/a.png", "data/table.csv", "WebApps/app.html", "entries/work/manual.html"):
            self.write(name, "<?php OUTSIDE_ASSET_MUST_NOT_BE_READ ?>")
        original = '<meta charset="Shift_JIS"><a href="/blog/">manual</a>'
        self.write("style/manual.html", original)
        self.write("style/a.css", 'a{background:url(/blog/style/bg.png)}')
        self.write("style/bg.png", "background")
        output = self.root.parent / "public"
        report = self.root.parent / "report.json"
        self.assertEqual(main(["--source", str(self.root), "--output", str(output), "--report", str(report)]), 0)
        self.assertEqual((output / "style/manual.html").read_bytes(), (self.root / "style/manual.html").read_bytes())
        self.assertIn('url("bg.png")', (output / "style/a.css").read_text(encoding="utf-8"))
        for name in ("image", "data", "WebApps", "entries"):
            self.assertFalse((output / name).exists())
        self.assertNotIn("local link target absent from output: /blog/", report.read_text(encoding="utf-8"))

    def test_authored_shift_jis_html_preserves_its_encoding(self):
        text = '<meta charset="Shift_JIS"><p>日本語の説明</p><img src="/blog/image/a.png">'
        raw = text.encode("cp932")
        decoded, encoding = decode_asset(raw)
        self.assertEqual(decoded, text)
        linker = LocalLinks(self.config, self.urls, {"image/a.png"})
        changed = linker.html(decoded, "style/readme.html", site_relative=False)
        self.assertIn('src="../image/a.png"', changed)
        self.assertIn("日本語の説明", changed.encode(encoding).decode("cp932"))

    def test_index_xml_owns_directory_entry_point_and_uses_its_skin(self):
        self.entry("work/index.xml", "Cover", "2025-01-01", "Cover article")
        self.write("entries/work/html_body.skin", '<%=$site_items url="work/index.htm" num="1"%>')
        self.make_renderer()
        self.assertEqual(self.urls.output(Context("work/index.htm")), "work/index.htm")
        self.assertEqual(self.urls.output(Context("work/")), "work/index.htm")
        self.assertEqual(self.renderer.page(Context("work/")), self.renderer.page(Context("work/index.htm")))
        linker = LocalLinks(self.config, self.urls, {"work/index.htm"})
        self.assertEqual(linker.reference("/blog/work/", "other/a.htm"), "../work/index.htm")
        self.assertEqual(linker.reference("/blog/work/index.htm", "other/a.htm"), "../work/index.htm")
        output = self.root.parent / "public"
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 0)
        self.assertTrue((output / "work/index.htm").is_file())
        self.assertFalse((output / "work/_category.htm").exists())
        self.assertIn("Cover article", (output / "work/index.htm").read_text(encoding="utf-8"))

    def test_verbose_progress_is_stdout_and_default_stays_quiet(self):
        def run(*flags):
            capture = io.StringIO()
            with redirect_stdout(capture):
                code = main(["--source", str(self.root), "--check", *flags])
            self.assertEqual(code, 0)
            return capture.getvalue()
        quiet = run()
        self.assertNotIn("Scan entries and skin inheritance", quiet)
        verbose = run("-v")
        for phase in ("load configuration", "Scan entries", "Render HTML", "Collect static assets", "Convert HTML links", "Verify input", "Check complete"):
            self.assertIn(phase, verbose)
        self.assertNotIn("Read source:", verbose)
        self.assertIn("Read source:", run("-vv"))

    def test_unreleased_version_is_09751(self):
        self.assertEqual(__version__, "0.9.7.5.1")


if __name__ == "__main__":
    unittest.main()
