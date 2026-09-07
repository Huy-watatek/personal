from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.erp_telegram_notify.tools.html2tg import html_to_telegram


@tagged("post_install", "-at_install")
class TestHtml2Tg(BaseCase):

    def test_keeps_supported_tags(self):
        self.assertEqual(html_to_telegram("<b>b</b> <i>i</i>"), "<b>b</b> <i>i</i>")

    def test_normalises_aliases(self):
        self.assertEqual(html_to_telegram("<strong>a</strong><em>b</em>"), "<b>a</b><i>b</i>")

    def test_strips_unsupported_tags_keeping_text(self):
        self.assertEqual(html_to_telegram("<div><span>hello</span></div>"), "hello")

    def test_paragraphs_and_breaks_become_newlines(self):
        self.assertEqual(html_to_telegram("<p>one</p><p>two</p>"), "one\ntwo")
        self.assertEqual(html_to_telegram("a<br/>b"), "a\nb")

    def test_list_items_become_bullets(self):
        self.assertEqual(html_to_telegram("<ul><li>a</li><li>b</li></ul>"), "• a\n• b")

    def test_anchor_keeps_only_href(self):
        self.assertEqual(
            html_to_telegram('<a href="https://x.vn" class="btn">go</a>'),
            '<a href="https://x.vn">go</a>',
        )

    def test_anchor_without_href_is_dropped(self):
        self.assertEqual(html_to_telegram("<a>go</a>"), "go")

    def test_special_characters_stay_escaped(self):
        self.assertEqual(html_to_telegram("<b>A &amp; B</b>"), "<b>A &amp; B</b>")

    def test_collapses_excessive_blank_lines(self):
        self.assertEqual(html_to_telegram("<p>a</p><br/><br/><br/><p>b</p>"), "a\n\nb")

    def test_empty_input(self):
        self.assertEqual(html_to_telegram(None), "")
        self.assertEqual(html_to_telegram(""), "")

    def test_truncation_respects_limit_and_closes_tags(self):
        for limit in (10, 20, 30, 64, 200):
            out = html_to_telegram("<b>" + "x" * 500 + "</b>", limit=limit)
            self.assertLessEqual(len(out), limit, "overran limit %s" % limit)
            self.assertTrue(out.endswith("</b>"), "left <b> unclosed at limit %s" % limit)

    def test_truncation_closes_nested_tags_in_order(self):
        out = html_to_telegram("<b>bold <i>it " + "y" * 300 + "</i></b>", limit=40)
        self.assertLessEqual(len(out), 40)
        self.assertTrue(out.endswith("</i></b>"))

    def test_long_odoo_body_fits_telegram_cap(self):
        body = "<p>" + ("Điều khoản thanh toán thay đổi. " * 300) + "</p>"
        self.assertLessEqual(len(html_to_telegram(body)), 4096)
