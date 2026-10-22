"""Synthetic regression fixtures; no original site material is redistributed."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from rnote_static.build import main, safe_output
from rnote_static.common import BuildError, date_string, parse_date, reject_php, split_path, xml_tag
from rnote_static.config import Config, expression
from rnote_static.entries import Index
from rnote_static.render import Renderer
from rnote_static.selection import Context, select
from rnote_static.skins import Skins, find_tag, options
from rnote_static.urls import URLs, absolute_assets
from rnote_static.validation import check_links


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
        self.urls = URLs(self.config)
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
        self.assertEqual(self.urls.output(Context("work/", "2020-01", 1)), "work/_date/2020-01/_page/2/index.html")
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
        self.assertTrue((output / "work/_page/2/index.html").is_file())
        self.assertEqual((output / "index.html").read_bytes(), (output / "index.htm").read_bytes())
        self.assertTrue((output / "rss.rdf").is_file())
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 0)
        after = {str(p): hashlib.sha256(p.read_bytes()).digest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        old = (output / "index.html").read_bytes()
        self.write("entries/html_body.skin", "<?php forbidden ?>")
        self.assertEqual(main(["--source", str(self.root), "--output", str(output)]), 1)
        self.assertEqual((output / "index.html").read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
