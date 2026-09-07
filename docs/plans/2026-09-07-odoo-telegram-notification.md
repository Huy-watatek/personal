# Kế hoạch triển khai: Thông báo ERP qua Telegram
# Implementation Plan: ERP Notification via Telegram

> **Cho agent thực thi / For agentic workers:** Thực thi plan này theo từng task,
> không nhảy cóc. Các bước dùng cú pháp checkbox (`- [ ]`) để theo dõi tiến độ.
> EN: Execute this plan task-by-task, in order. Steps use checkbox syntax for tracking.

**Mục tiêu / Goal:** Xây addon Odoo 19 `erp_telegram_notify` cho phép Odoo đẩy thông báo vào group Telegram khi dữ liệu thay đổi, và nhận lệnh ngược từ Telegram (đăng ký kênh, duyệt/từ chối record).
EN: Build an Odoo 19 addon `erp_telegram_notify` that pushes notifications to Telegram groups when records change, and accepts inbound commands from Telegram (channel registration, approve/reject actions).

**Kiến trúc / Architecture:** Tái dùng engine trigger sẵn có của Odoo — ta chỉ thêm một loại `ir.actions.server` mới (`state = 'telegram'`) để `base.automation` gọi được. Mọi tin nhắn đi qua hàng đợi `telegram.outbox` ghi trong cùng transaction nghiệp vụ, rồi được đẩy đi ở `cr.postcommit` (đường nhanh) với `ir.cron` làm lưới an toàn cho retry. Chiều inbound là một controller public nhận webhook của Telegram, xác thực bằng header bí mật.
EN: Reuse Odoo's existing trigger engine — we only add a new `ir.actions.server` type (`state = 'telegram'`) that `base.automation` can invoke. Every message goes through a `telegram.outbox` queue written inside the business transaction, then flushed on `cr.postcommit` (fast path) with an `ir.cron` safety net for retries. Inbound is a public controller receiving Telegram webhooks, authenticated by a secret header.

**Công nghệ / Tech Stack:** Odoo 19.0, Python 3.11+, `requests`, Telegram Bot API, `base_automation`, `mail`

**Spec:** Chốt trong hội thoại thiết kế ngày 2026-09-07 (xem mục "Phạm vi" bên dưới).
EN: Settled in the design discussion of 2026-09-07 (see "Scope" below).

## Phạm vi / Scope

Trong phạm vi / In scope:
- Outbound: Odoo → bot Telegram → group (kèm topic/thread), cấu hình bằng `base.automation` trên UI.
- Inbound: webhook công khai, lệnh `/register` tự tạo kênh, nút inline duyệt/từ chối.
- Hàng đợi có retry, tôn trọng `429 retry_after`, gộp tin trùng, công tắc tắt toàn cục.

Ngoài phạm vi / Out of scope:
- Zalo ZNS (sẽ là plan riêng / separate plan).
- Chat hai chiều đầy đủ kiểu gateway (reply Telegram đẩy vào chatter) — chỉ làm lệnh và nút, không làm relay hội thoại.

## Ràng buộc toàn cục / Global Constraints

Mọi task đều ngầm chịu các ràng buộc sau.
EN: Every task is implicitly bound by the following.

- Odoo phiên bản đúng `19.0`. Không dùng API đã bỏ ở 19 (`type='json'` trong controller đã đổi thành `type='jsonrpc'`; webhook Telegram gửi JSON thuần nên PHẢI dùng `type='http'`).
  EN: Odoo exactly `19.0`. Telegram posts plain JSON, not JSON-RPC, so controllers MUST use `type='http'`.
- Tên addon: `erp_telegram_notify`. Đặt tại `addons/erp_telegram_notify/`.
- KHÔNG gọi HTTP ra ngoài bên trong transaction ghi dữ liệu. Mọi lần gửi phải đi qua `telegram.outbox`.
  EN: NEVER perform outbound HTTP inside a data-writing transaction. All sends go through `telegram.outbox`.
- Mọi request tới Telegram đặt `timeout=10` giây.
  EN: Every request to Telegram uses `timeout=10` seconds.
- Token bot lưu ở field có `groups='base.group_system'`. Không bao giờ ghi token vào log.
  EN: Bot tokens live on a field with `groups='base.group_system'`. Never log a token.
- Giới hạn Telegram: 4096 ký tự/tin, 20 tin/phút/group. Phải tôn trọng `parameters.retry_after` khi nhận `429`.
  EN: Telegram limits: 4096 chars per message, 20 messages/minute per group. Must honour `parameters.retry_after` on `429`.
- Lệnh chạy test / test command:
  `odoo -d <db> -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
- Commit sau mỗi task. Message theo Conventional Commits, tiếng Anh.
  EN: Commit after every task, Conventional Commits style, in English.

---

## Cấu trúc file / File Structure

```
addons/erp_telegram_notify/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── webhook.py              # Controller public nhận update từ Telegram
├── models/
│   ├── __init__.py
│   ├── telegram_bot.py         # Thông tin bot: token, secret, kill switch
│   ├── telegram_channel.py     # Điểm đến: chat_id + thread_id
│   ├── telegram_outbox.py      # Hàng đợi gửi, retry, backoff
│   ├── telegram_button.py      # Allowlist các method được phép gọi từ nút inline
│   ├── ir_actions_server.py    # Thêm state 'telegram' cho base.automation
│   └── res_users.py            # Map user Odoo ↔ user Telegram
├── tools/
│   ├── __init__.py
│   ├── html2tg.py              # Chuyển HTML của Odoo sang HTML Telegram chấp nhận
│   └── telegram_api.py         # Client HTTP thuần, không phụ thuộc ORM
├── data/
│   └── ir_cron.xml             # Cron quét outbox
├── security/
│   ├── ir.model.access.csv
│   └── telegram_security.xml
└── views/
    ├── telegram_bot_views.xml
    ├── telegram_channel_views.xml
    ├── telegram_outbox_views.xml
    ├── ir_actions_server_views.xml
    └── menus.xml

tests/  → addons/erp_telegram_notify/tests/
├── __init__.py
├── test_html2tg.py
├── test_telegram_api.py
├── test_outbox.py
├── test_server_action.py
├── test_debounce.py
└── test_webhook.py
```

Nguyên tắc phân rã / Decomposition rationale: `tools/` là code thuần Python không đụng ORM nên test được cực nhanh và tách bạch; `models/` chia theo trách nhiệm chứ không theo tầng; controller tách riêng vì nó là bề mặt công khai duy nhất và cần soi kỹ về bảo mật.
EN: `tools/` is pure Python with no ORM dependency, so it tests fast and in isolation; `models/` is split by responsibility, not by technical layer; the controller is separate because it is the only public surface and needs focused security review.

---

## Task 1: Scaffold addon và model `telegram.bot`
## Task 1: Addon scaffold and `telegram.bot` model

**Files:**
- Create: `addons/erp_telegram_notify/__init__.py`
- Create: `addons/erp_telegram_notify/__manifest__.py`
- Create: `addons/erp_telegram_notify/models/__init__.py`
- Create: `addons/erp_telegram_notify/models/telegram_bot.py`
- Create: `addons/erp_telegram_notify/security/ir.model.access.csv`
- Create: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_bot.py`

**Interfaces:**
- Consumes: không có / none (task đầu tiên)
- Produces:
  - Model `telegram.bot` với các field: `name` (Char), `token` (Char, `groups='base.group_system'`), `webhook_secret` (Char, `groups='base.group_system'`), `bot_username` (Char), `active` (Boolean), `enabled` (Boolean, kill switch toàn cục)
  - `telegram.bot._get_default_bot() -> recordset` trả về bot đang bật đầu tiên

- [ ] **Bước 1: Tạo scaffold addon / Create the addon scaffold**

Tạo `addons/erp_telegram_notify/__manifest__.py`:

```python
{
    "name": "ERP Telegram Notify",
    "version": "19.0.1.0.0",
    "summary": "Push ERP notifications to Telegram groups and accept inbound commands",
    "license": "LGPL-3",
    "depends": ["base", "base_automation", "mail"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
}
```

Tạo `addons/erp_telegram_notify/__init__.py`:

```python
from . import models
```

Tạo `addons/erp_telegram_notify/models/__init__.py`:

```python
from . import telegram_bot
```

Tạo `addons/erp_telegram_notify/tests/__init__.py`:

```python
from . import test_bot
```

- [ ] **Bước 2: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_bot.py`:

```python
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tests import tagged
from odoo.exceptions import AccessError


@tagged("post_install", "-at_install")
class TestTelegramBot(TransactionCase):

    def test_bot_creation_defaults(self):
        bot = self.env["telegram.bot"].create({
            "name": "ERP Bot",
            "token": "123456:AAEtest",
        })
        self.assertTrue(bot.active)
        self.assertTrue(bot.enabled)
        self.assertTrue(bot.webhook_secret, "webhook_secret must be auto-generated")
        self.assertEqual(len(bot.webhook_secret), 32)

    def test_token_hidden_from_non_system_user(self):
        self.env["telegram.bot"].create({"name": "ERP Bot", "token": "123456:AAEtest"})
        user = new_test_user(self.env, login="tg_reader", groups="base.group_user")
        with self.assertRaises(AccessError):
            self.env["telegram.bot"].with_user(user).search([]).read(["token"])

    def test_get_default_bot_skips_disabled(self):
        Bot = self.env["telegram.bot"]
        Bot.search([]).write({"enabled": False})
        off = Bot.create({"name": "Off", "token": "1:A", "enabled": False})
        on = Bot.create({"name": "On", "token": "2:B", "enabled": True})
        self.assertEqual(Bot._get_default_bot(), on)
        self.assertNotEqual(Bot._get_default_bot(), off)
```

- [ ] **Bước 3: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -i erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `KeyError: 'telegram.bot'` (model chưa tồn tại / model does not exist yet)

- [ ] **Bước 4: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/models/telegram_bot.py`:

```python
import secrets

from odoo import api, fields, models


class TelegramBot(models.Model):
    _name = "telegram.bot"
    _description = "Telegram Bot"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    token = fields.Char(
        string="Bot Token",
        required=True,
        groups="base.group_system",
        help="Token issued by @BotFather. Never exposed to non-system users.",
    )
    webhook_secret = fields.Char(
        string="Webhook Secret",
        groups="base.group_system",
        default=lambda self: secrets.token_hex(16),
        help="Sent by Telegram in the X-Telegram-Bot-Api-Secret-Token header.",
    )
    bot_username = fields.Char(string="Bot Username")
    active = fields.Boolean(default=True)
    enabled = fields.Boolean(
        string="Sending Enabled",
        default=True,
        help="Global kill switch. Turn off to stop all outbound traffic "
             "without uninstalling (e.g. when Telegram is blocked by the ISP).",
    )

    @api.model
    def _get_default_bot(self):
        return self.search([("enabled", "=", True)], limit=1)
```

Tạo `addons/erp_telegram_notify/security/ir.model.access.csv`:

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_telegram_bot_system,telegram.bot.system,model_telegram_bot,base.group_system,1,1,1,1
```

- [ ] **Bước 5: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -i erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 3 tests

- [ ] **Bước 6: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add addon scaffold and telegram.bot model"
```

---

## Task 2: Bộ chuyển HTML Odoo → HTML Telegram
## Task 2: Odoo HTML → Telegram HTML converter

**Bối cảnh / Context:** Telegram `parse_mode=HTML` chỉ chấp nhận `b i u s a code pre blockquote tg-spoiler` và các bí danh của chúng. Body chatter của Odoo đầy `<p> <div> <ul> <table>` — gửi thẳng sẽ nhận `400 Bad Request: can't parse entities`. Đây là nguồn lỗi số một của mọi tích hợp Telegram nên task này được tách riêng và test kỹ.
EN: Telegram's HTML mode accepts only a small tag subset. Odoo chatter bodies are full of unsupported tags; sending them raw returns `400 Bad Request: can't parse entities`. This is the number-one failure source in Telegram integrations, hence a dedicated, heavily tested task.

**Files:**
- Create: `addons/erp_telegram_notify/tools/__init__.py`
- Create: `addons/erp_telegram_notify/tools/html2tg.py`
- Modify: `addons/erp_telegram_notify/__init__.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_html2tg.py`

**Interfaces:**
- Consumes: không có / none (thuần Python, không đụng ORM)
- Produces: `html_to_telegram(html: str, limit: int = 4096) -> str`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_html2tg.py`:

```python
from odoo.tests.common import BaseCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools.html2tg import html_to_telegram


@tagged("post_install", "-at_install")
class TestHtml2Tg(BaseCase):

    def test_keeps_supported_tags(self):
        self.assertEqual(
            html_to_telegram("<b>bold</b> and <i>italic</i>"),
            "<b>bold</b> and <i>italic</i>",
        )

    def test_strips_unsupported_tags_but_keeps_text(self):
        self.assertEqual(
            html_to_telegram("<div><span>hello</span></div>"),
            "hello",
        )

    def test_paragraphs_become_newlines(self):
        self.assertEqual(
            html_to_telegram("<p>one</p><p>two</p>"),
            "one\ntwo",
        )

    def test_list_items_become_bullets(self):
        self.assertEqual(
            html_to_telegram("<ul><li>a</li><li>b</li></ul>"),
            "• a\n• b",
        )

    def test_br_becomes_newline(self):
        self.assertEqual(html_to_telegram("a<br/>b"), "a\nb")

    def test_anchor_keeps_only_href(self):
        self.assertEqual(
            html_to_telegram('<a href="https://x.vn" class="btn" target="_blank">go</a>'),
            '<a href="https://x.vn">go</a>',
        )

    def test_anchor_without_href_is_dropped(self):
        self.assertEqual(html_to_telegram("<a>go</a>"), "go")

    def test_escapes_bare_special_characters(self):
        self.assertEqual(html_to_telegram("5 < 6 & 7 > 2"), "5 &lt; 6 &amp; 7 &gt; 2")

    def test_collapses_excessive_blank_lines(self):
        self.assertEqual(html_to_telegram("<p>a</p><br/><br/><br/><p>b</p>"), "a\n\nb")

    def test_truncates_and_closes_open_tags(self):
        out = html_to_telegram("<b>" + "x" * 100 + "</b>", limit=20)
        self.assertTrue(out.endswith("</b>"))
        self.assertTrue(out.startswith("<b>xxx"))
        self.assertLessEqual(len(out), 20)

    def test_handles_none_and_empty(self):
        self.assertEqual(html_to_telegram(None), "")
        self.assertEqual(html_to_telegram(""), "")

    def test_alias_tags_normalised(self):
        self.assertEqual(html_to_telegram("<strong>a</strong><em>b</em>"), "<b>a</b><i>b</i>")
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `ModuleNotFoundError: No module named 'odoo.addons.erp_telegram_notify.tools'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/tools/__init__.py`:

```python
from . import html2tg
```

Sửa `addons/erp_telegram_notify/__init__.py` thành:

```python
from . import models
from . import tools
```

Sửa `addons/erp_telegram_notify/tests/__init__.py` thành:

```python
from . import test_bot
from . import test_html2tg
```

Tạo `addons/erp_telegram_notify/tools/html2tg.py`:

```python
"""Convert Odoo rich HTML into the small HTML subset Telegram accepts.

Telegram's ``parse_mode=HTML`` supports only: b, strong, i, em, u, ins, s,
strike, del, a, code, pre, blockquote, tg-spoiler. Anything else must be
stripped, and bare <, > and & in text must be escaped.
"""

import re
from html import escape
from html.parser import HTMLParser

# Tag name -> canonical Telegram tag name.
KEEP = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code",
    "pre": "pre",
    "blockquote": "blockquote",
    "tg-spoiler": "tg-spoiler",
    "a": "a",
}

# Tags that produce a line break when they close.
BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

MAX_LEN = 4096


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "li":
            self.parts.append("• ")
            return
        keep = KEEP.get(tag)
        if not keep:
            return
        if keep == "a":
            href = dict(attrs).get("href")
            if not href:
                return
            self.parts.append('<a href="%s">' % escape(href, quote=True))
        else:
            self.parts.append("<%s>" % keep)
        self.open_tags.append(keep)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in BLOCK:
            self.parts.append("\n")
            return
        keep = KEEP.get(tag)
        if not keep or keep not in self.open_tags:
            return
        # Close everything opened after this tag, then reopen nothing:
        # malformed nesting is resolved by closing greedily.
        while self.open_tags:
            last = self.open_tags.pop()
            self.parts.append("</%s>" % last)
            if last == keep:
                break

    def handle_data(self, data):
        self.parts.append(escape(data, quote=False))

    def close_all(self):
        while self.open_tags:
            self.parts.append("</%s>" % self.open_tags.pop())


def _truncate(text, limit):
    """Cut ``text`` to ``limit`` characters without leaving a tag unclosed."""
    if len(text) <= limit:
        return text
    stack = []
    out = []
    used = 0
    for token in re.split(r"(<[^>]+>)", text):
        if not token:
            continue
        if token.startswith("<"):
            out.append(token)
            name = re.match(r"</?\s*([a-zA-Z0-9-]+)", token)
            if name:
                if token.startswith("</"):
                    if stack and stack[-1] == name.group(1):
                        stack.pop()
                else:
                    stack.append(name.group(1))
            continue
        closing_cost = sum(len(t) + 3 for t in stack) + 1  # "</tag>" + ellipsis
        room = limit - used - closing_cost
        if room <= 0:
            break
        if len(token) > room:
            out.append(token[:room])
            used += room
            break
        out.append(token)
        used += len(token)
    out.append("…")
    while stack:
        out.append("</%s>" % stack.pop())
    return "".join(out)


def html_to_telegram(html, limit=MAX_LEN):
    """Return ``html`` reduced to Telegram-safe markup, at most ``limit`` chars."""
    if not html:
        return ""
    parser = _Converter()
    parser.feed(html)
    parser.close()
    parser.close_all()
    text = "".join(parser.parts)
    # Normalise whitespace: no trailing spaces, at most one blank line.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return _truncate(text, limit)
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 12 tests trong `TestHtml2Tg` / 12 tests in `TestHtml2Tg`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify/tools addons/erp_telegram_notify/tests/test_html2tg.py addons/erp_telegram_notify/__init__.py addons/erp_telegram_notify/tests/__init__.py
git commit -m "feat(telegram): convert Odoo HTML to Telegram-safe markup"
```

---
## Task 3: Client HTTP Telegram và model `telegram.channel`
## Task 3: Telegram HTTP client and `telegram.channel` model

**Files:**
- Create: `addons/erp_telegram_notify/tools/telegram_api.py`
- Create: `addons/erp_telegram_notify/models/telegram_channel.py`
- Modify: `addons/erp_telegram_notify/tools/__init__.py`
- Modify: `addons/erp_telegram_notify/models/__init__.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Modify: `addons/erp_telegram_notify/security/ir.model.access.csv`
- Test: `addons/erp_telegram_notify/tests/test_telegram_api.py`

**Interfaces:**
- Consumes: `telegram.bot` (Task 1) — đọc `token`
- Produces:
  - `class TelegramError(Exception)` với thuộc tính `description: str`, `error_code: int | None`, `retry_after: int | None`
  - `call(token: str, method: str, payload: dict, timeout: int = 10) -> dict` trả về nội dung khoá `result`
  - Model `telegram.channel` với field: `name` (Char), `bot_id` (Many2one `telegram.bot`), `chat_id` (Char), `thread_id` (Integer), `active` (Boolean), `state` (Selection `pending`/`confirmed`)
  - `telegram.channel.action_send_test() -> None` gửi một tin thử

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_telegram_api.py`:

```python
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools import telegram_api


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@tagged("post_install", "-at_install")
class TestTelegramApi(TransactionCase):

    def test_call_returns_result_payload(self):
        fake = _FakeResponse({"ok": True, "result": {"message_id": 7}})
        with patch.object(telegram_api.requests, "post", return_value=fake) as post:
            result = telegram_api.call("TOKEN", "sendMessage", {"chat_id": "-100"})
        self.assertEqual(result, {"message_id": 7})
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertIn("/botTOKEN/sendMessage", post.call_args.args[0])

    def test_call_raises_with_description(self):
        fake = _FakeResponse(
            {"ok": False, "error_code": 400, "description": "can't parse entities"},
            status_code=400,
        )
        with patch.object(telegram_api.requests, "post", return_value=fake):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertEqual(ctx.exception.error_code, 400)
        self.assertIn("parse entities", ctx.exception.description)
        self.assertIsNone(ctx.exception.retry_after)

    def test_call_extracts_retry_after_on_429(self):
        fake = _FakeResponse(
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 37},
            },
            status_code=429,
        )
        with patch.object(telegram_api.requests, "post", return_value=fake):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertEqual(ctx.exception.retry_after, 37)

    def test_call_wraps_network_error(self):
        with patch.object(
            telegram_api.requests, "post",
            side_effect=telegram_api.requests.exceptions.Timeout("timed out"),
        ):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("TOKEN", "sendMessage", {})
        self.assertIsNone(ctx.exception.error_code)
        self.assertIn("timed out", ctx.exception.description)

    def test_token_never_appears_in_exception(self):
        with patch.object(
            telegram_api.requests, "post",
            side_effect=telegram_api.requests.exceptions.ConnectionError("boom TOKEN"),
        ):
            with self.assertRaises(telegram_api.TelegramError) as ctx:
                telegram_api.call("SECRETTOKEN", "sendMessage", {})
        self.assertNotIn("SECRETTOKEN", str(ctx.exception))


@tagged("post_install", "-at_install")
class TestTelegramChannel(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})

    def test_channel_send_test_calls_api(self):
        channel = self.env["telegram.channel"].create({
            "name": "HR Group",
            "bot_id": self.bot.id,
            "chat_id": "-1001234567890",
            "thread_id": 42,
        })
        with patch.object(
            telegram_api, "call", return_value={"message_id": 1}
        ) as call:
            channel.action_send_test()
        self.assertEqual(call.call_args.args[1], "sendMessage")
        payload = call.call_args.args[2]
        self.assertEqual(payload["chat_id"], "-1001234567890")
        self.assertEqual(payload["message_thread_id"], 42)

    def test_channel_omits_thread_id_when_zero(self):
        channel = self.env["telegram.channel"].create({
            "name": "General",
            "bot_id": self.bot.id,
            "chat_id": "-100999",
        })
        self.assertNotIn("message_thread_id", channel._base_payload())
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `ModuleNotFoundError: No module named 'odoo.addons.erp_telegram_notify.tools.telegram_api'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/tools/telegram_api.py`:

```python
"""Thin HTTP client for the Telegram Bot API.

Deliberately free of any ORM dependency so it can be unit-tested in isolation
and reused from both the outbox worker and the inbound webhook controller.
"""

import logging

import requests

_logger = logging.getLogger(__name__)

BASE_URL = "https://api.telegram.org"
DEFAULT_TIMEOUT = 10


class TelegramError(Exception):
    """Raised for both API-level errors and transport failures."""

    def __init__(self, description, error_code=None, retry_after=None):
        self.description = description
        self.error_code = error_code
        self.retry_after = retry_after
        super().__init__(description)


def call(token, method, payload, timeout=DEFAULT_TIMEOUT):
    """Invoke ``method`` on the Bot API and return the ``result`` payload.

    :raises TelegramError: on transport failure or a non-ok API response.
    """
    url = "%s/bot%s/%s" % (BASE_URL, token, method)
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        # Never let the token leak through an exception message.
        message = str(exc).replace(token, "***")
        _logger.warning("Telegram transport error on %s: %s", method, message)
        raise TelegramError(message) from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise TelegramError(
            "Non-JSON response (HTTP %s)" % response.status_code
        ) from exc

    if body.get("ok"):
        return body.get("result")

    parameters = body.get("parameters") or {}
    raise TelegramError(
        body.get("description") or "Unknown Telegram error",
        error_code=body.get("error_code"),
        retry_after=parameters.get("retry_after"),
    )
```

Sửa `addons/erp_telegram_notify/tools/__init__.py` thành:

```python
from . import html2tg
from . import telegram_api
```

Tạo `addons/erp_telegram_notify/models/telegram_channel.py`:

```python
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools import telegram_api


class TelegramChannel(models.Model):
    _name = "telegram.channel"
    _description = "Telegram Destination Channel"
    _order = "name"

    name = fields.Char(required=True)
    bot_id = fields.Many2one(
        "telegram.bot", required=True, ondelete="cascade",
        default=lambda self: self.env["telegram.bot"]._get_default_bot(),
    )
    chat_id = fields.Char(
        required=True,
        help="Telegram chat id. Group and supergroup ids are negative, e.g. -1001234567890.",
    )
    thread_id = fields.Integer(
        string="Topic ID",
        help="Forum topic (message_thread_id). Leave at 0 for the main thread.",
    )
    state = fields.Selection(
        [("pending", "Pending"), ("confirmed", "Confirmed")],
        default="confirmed", required=True,
        help="Channels auto-created by the /register command start as Pending "
             "and must be confirmed by an administrator before they receive traffic.",
    )
    active = fields.Boolean(default=True)

    _chat_thread_uniq = models.Constraint(
        "UNIQUE(bot_id, chat_id, thread_id)",
        "This bot already has a channel for that chat and topic.",
    )

    def _base_payload(self):
        """Return the chat routing fields shared by every outgoing message."""
        self.ensure_one()
        payload = {"chat_id": self.chat_id}
        if self.thread_id:
            payload["message_thread_id"] = self.thread_id
        return payload

    def action_send_test(self):
        """Send a probe message so an administrator can verify the wiring."""
        self.ensure_one()
        token = self.bot_id.sudo().token
        if not token:
            raise UserError(_("Bot %s has no token configured.", self.bot_id.display_name))
        payload = self._base_payload()
        payload.update({
            "text": _("✅ Test message from Odoo (%s).", self.env.cr.dbname),
            "parse_mode": "HTML",
        })
        try:
            telegram_api.call(token, "sendMessage", payload)
        except telegram_api.TelegramError as exc:
            raise UserError(_("Telegram refused the test message: %s", exc.description)) from exc
```

Sửa `addons/erp_telegram_notify/models/__init__.py` thành:

```python
from . import telegram_bot
from . import telegram_channel
```

Sửa `addons/erp_telegram_notify/tests/__init__.py` thành:

```python
from . import test_bot
from . import test_html2tg
from . import test_telegram_api
```

Thêm dòng vào `addons/erp_telegram_notify/security/ir.model.access.csv`:

```csv
access_telegram_channel_user,telegram.channel.user,model_telegram_channel,base.group_user,1,0,0,0
access_telegram_channel_system,telegram.channel.system,model_telegram_channel,base.group_system,1,1,1,1
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 7 tests mới / 7 new tests

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add Bot API client and destination channel model"
```

---

## Task 4: Hàng đợi `telegram.outbox` với retry và backoff
## Task 4: `telegram.outbox` queue with retry and backoff

**Bối cảnh / Context:** Gọi HTTP trong transaction ghi dữ liệu là sai lầm nghiêm trọng: nếu transaction rollback, tin nhắn đã bay đi và không rút lại được. Ta ghi vào outbox trong transaction, đẩy đi ở `cr.postcommit` (độ trễ ~1 giây), và để `ir.cron` quét lại những gì thất bại.
EN: HTTP inside the writing transaction is a serious mistake: on rollback the message is already gone and cannot be recalled. We write to the outbox inside the transaction, flush on `cr.postcommit` (~1s latency), and let `ir.cron` retry whatever failed.

**Files:**
- Create: `addons/erp_telegram_notify/models/telegram_outbox.py`
- Create: `addons/erp_telegram_notify/data/ir_cron.xml`
- Modify: `addons/erp_telegram_notify/models/__init__.py`
- Modify: `addons/erp_telegram_notify/__manifest__.py`
- Modify: `addons/erp_telegram_notify/security/ir.model.access.csv`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_outbox.py`

**Interfaces:**
- Consumes: `telegram.channel._base_payload()` (Task 3), `telegram_api.call()` và `telegram_api.TelegramError` (Task 3), `telegram.bot.enabled` (Task 1)
- Produces:
  - Model `telegram.outbox` với field: `channel_id`, `body` (Text), `reply_markup` (Text, JSON), `res_model` (Char), `res_id` (Integer), `state` (Selection `pending`/`sent`/`failed`), `retry_count` (Integer), `next_retry_at` (Datetime), `last_error` (Text), `telegram_message_id` (Integer)
  - `telegram.outbox._enqueue(channel, body, res_model=None, res_id=None, reply_markup=None) -> recordset`
  - `telegram.outbox._flush(limit=50) -> None` — quét và gửi
  - `telegram.outbox._cron_flush() -> None` — điểm vào của cron
  - Hằng số `RETRY_DELAYS: list[int]` và `MAX_RETRY: int`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_outbox.py`:

```python
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestOutbox(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.channel = self.env["telegram.channel"].create({
            "name": "Ops", "bot_id": self.bot.id, "chat_id": "-100777", "thread_id": 5,
        })
        self.Outbox = self.env["telegram.outbox"]

    def test_enqueue_creates_pending_row(self):
        msg = self.Outbox._enqueue(self.channel, "<b>hi</b>")
        self.assertEqual(msg.state, "pending")
        self.assertEqual(msg.retry_count, 0)
        self.assertEqual(msg.body, "<b>hi</b>")

    def test_flush_marks_sent_and_stores_message_id(self):
        msg = self.Outbox._enqueue(self.channel, "hi")
        with patch.object(telegram_api, "call", return_value={"message_id": 99}) as call:
            self.Outbox._flush()
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.telegram_message_id, 99)
        payload = call.call_args.args[2]
        self.assertEqual(payload["chat_id"], "-100777")
        self.assertEqual(payload["message_thread_id"], 5)
        self.assertEqual(payload["parse_mode"], "HTML")

    def test_flush_schedules_retry_on_error(self):
        msg = self.Outbox._enqueue(self.channel, "hi")
        with patch.object(
            telegram_api, "call",
            side_effect=telegram_api.TelegramError("boom", error_code=500),
        ):
            self.Outbox._flush()
        self.assertEqual(msg.state, "pending")
        self.assertEqual(msg.retry_count, 1)
        self.assertIn("boom", msg.last_error)
        self.assertGreater(msg.next_retry_at, fields.Datetime.now())

    def test_flush_honours_retry_after_on_429(self):
        msg = self.Outbox._enqueue(self.channel, "hi")
        with patch.object(
            telegram_api, "call",
            side_effect=telegram_api.TelegramError("slow down", error_code=429, retry_after=120),
        ):
            self.Outbox._flush()
        delay = msg.next_retry_at - fields.Datetime.now()
        self.assertGreater(delay, timedelta(seconds=110))
        self.assertLess(delay, timedelta(seconds=130))

    def test_flush_gives_up_after_max_retry(self):
        from odoo.addons.erp_telegram_notify.models.telegram_outbox import MAX_RETRY
        msg = self.Outbox._enqueue(self.channel, "hi")
        msg.retry_count = MAX_RETRY - 1
        with patch.object(
            telegram_api, "call",
            side_effect=telegram_api.TelegramError("boom", error_code=400),
        ):
            self.Outbox._flush()
        self.assertEqual(msg.state, "failed")

    def test_flush_skips_rows_not_yet_due(self):
        msg = self.Outbox._enqueue(self.channel, "hi")
        msg.next_retry_at = fields.Datetime.now() + timedelta(hours=1)
        with patch.object(telegram_api, "call") as call:
            self.Outbox._flush()
        call.assert_not_called()
        self.assertEqual(msg.state, "pending")

    def test_kill_switch_blocks_sending(self):
        msg = self.Outbox._enqueue(self.channel, "hi")
        self.bot.enabled = False
        with patch.object(telegram_api, "call") as call:
            self.Outbox._flush()
        call.assert_not_called()
        self.assertEqual(msg.state, "pending")

    def test_reply_markup_is_forwarded_as_json(self):
        markup = '{"inline_keyboard": [[{"text": "Open", "url": "https://x.vn"}]]}'
        self.Outbox._enqueue(self.channel, "hi", reply_markup=markup)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush()
        self.assertEqual(call.call_args.args[2]["reply_markup"], markup)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `KeyError: 'telegram.outbox'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/models/telegram_outbox.py`:

```python
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..tools import telegram_api

_logger = logging.getLogger(__name__)

# Backoff schedule in seconds: 1min, 5min, 30min, 2h, 6h.
RETRY_DELAYS = [60, 300, 1800, 7200, 21600]
MAX_RETRY = len(RETRY_DELAYS)


class TelegramOutbox(models.Model):
    _name = "telegram.outbox"
    _description = "Telegram Outgoing Message Queue"
    _order = "id"

    channel_id = fields.Many2one("telegram.channel", required=True, ondelete="cascade")
    body = fields.Text(required=True)
    reply_markup = fields.Text(help="Serialised Telegram InlineKeyboardMarkup, if any.")
    res_model = fields.Char(index=True)
    res_id = fields.Integer(index=True)
    state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        default="pending", required=True, index=True,
    )
    retry_count = fields.Integer(default=0)
    next_retry_at = fields.Datetime(index=True)
    last_error = fields.Text()
    telegram_message_id = fields.Integer(readonly=True)

    @api.model
    def _enqueue(self, channel, body, res_model=None, res_id=None, reply_markup=None):
        """Queue one message. Safe to call inside a business transaction."""
        return self.create({
            "channel_id": channel.id,
            "body": body,
            "reply_markup": reply_markup,
            "res_model": res_model,
            "res_id": res_id,
        })

    def _payload(self):
        """Build the sendMessage payload for this queued row."""
        self.ensure_one()
        payload = self.channel_id._base_payload()
        payload.update({
            "text": self.body,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if self.reply_markup:
            payload["reply_markup"] = self.reply_markup
        return payload

    def _schedule_retry(self, error):
        """Move the row to its next attempt, or give up past MAX_RETRY."""
        self.ensure_one()
        retry_count = self.retry_count + 1
        if retry_count >= MAX_RETRY:
            self.write({
                "state": "failed",
                "retry_count": retry_count,
                "last_error": error.description,
            })
            return
        if error.retry_after:
            delay = error.retry_after
        else:
            delay = RETRY_DELAYS[retry_count - 1]
        self.write({
            "retry_count": retry_count,
            "last_error": error.description,
            "next_retry_at": fields.Datetime.now() + timedelta(seconds=delay),
        })

    @api.model
    def _flush(self, limit=50):
        """Send every due pending message. Never raises."""
        now = fields.Datetime.now()
        messages = self.search(
            [
                ("state", "=", "pending"),
                "|", ("next_retry_at", "=", False), ("next_retry_at", "<=", now),
                ("channel_id.bot_id.enabled", "=", True),
                ("channel_id.state", "=", "confirmed"),
            ],
            limit=limit,
        )
        for message in messages:
            token = message.channel_id.bot_id.sudo().token
            if not token:
                continue
            try:
                result = telegram_api.call(token, "sendMessage", message._payload())
            except telegram_api.TelegramError as exc:
                message._schedule_retry(exc)
                continue
            message.write({
                "state": "sent",
                "last_error": False,
                "telegram_message_id": (result or {}).get("message_id", 0),
            })

    @api.model
    def _cron_flush(self):
        """Entry point for the scheduled action."""
        self._flush(limit=200)

    @api.model
    def _flush_after_commit(self):
        """Register a postcommit hook so queued rows leave within ~1 second.

        The cron remains the safety net: if this hook fails, the rows stay
        pending and are picked up on the next cron pass.
        """
        def _run():
            with self.pool.cursor() as cr:
                env = self.env(cr=cr)
                try:
                    env["telegram.outbox"]._flush()
                except Exception:  # noqa: BLE001 - a notification must never break business flow
                    _logger.exception("Telegram outbox postcommit flush failed")

        self.env.cr.postcommit.add(_run)
```

Tạo `addons/erp_telegram_notify/data/ir_cron.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="ir_cron_telegram_flush" model="ir.cron">
        <field name="name">Telegram: flush outbox</field>
        <field name="model_id" ref="model_telegram_outbox"/>
        <field name="state">code</field>
        <field name="code">model._cron_flush()</field>
        <field name="interval_number">1</field>
        <field name="interval_type">minutes</field>
        <field name="active" eval="True"/>
    </record>
</odoo>
```

Sửa `addons/erp_telegram_notify/models/__init__.py` thành:

```python
from . import telegram_bot
from . import telegram_channel
from . import telegram_outbox
```

Sửa khoá `data` trong `addons/erp_telegram_notify/__manifest__.py` thành:

```python
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
```

Thêm dòng vào `addons/erp_telegram_notify/security/ir.model.access.csv`:

```csv
access_telegram_outbox_system,telegram.outbox.system,model_telegram_outbox,base.group_system,1,1,1,1
```

Sửa `addons/erp_telegram_notify/tests/__init__.py` thành:

```python
from . import test_bot
from . import test_html2tg
from . import test_telegram_api
from . import test_outbox
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 8 tests trong `TestOutbox` / 8 tests in `TestOutbox`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add outbox queue with backoff and retry_after handling"
```

---
## Task 5: Loại server action `telegram` cho `base.automation`
## Task 5: `telegram` server action type for `base.automation`

**Bối cảnh / Context:** Odoo đã có sẵn engine trigger (on create / on write / theo lịch / domain filter). Ta không viết lại nó — chỉ thêm một giá trị vào `ir.actions.server.state` và hiện thực `_run_action_telegram_multi`. Đây đúng là pattern module `mail` dùng cho `mail_post` (xem `addons/mail/models/ir_actions_server.py`).
EN: Odoo already ships the trigger engine. We do not reimplement it — we add one value to `ir.actions.server.state` and implement `_run_action_telegram_multi`, exactly the pattern the `mail` module uses for `mail_post`.

**Quyết định thiết kế / Design decision:** Chỉ có hai mức nội dung, `link_only` và `full`. Mức `summary` từng cân nhắc đã bị loại vì `base.automation` không truyền giá trị cũ của field vào server action, nên "tóm tắt thay đổi" không thể dựng chính xác — làm nửa vời sẽ gây hiểu nhầm (YAGNI).
EN: Only two content levels, `link_only` and `full`. The once-considered `summary` level is dropped: `base.automation` does not hand old field values to the server action, so a "what changed" summary cannot be built accurately, and a half-accurate one misleads (YAGNI).

**Files:**
- Create: `addons/erp_telegram_notify/models/ir_actions_server.py`
- Modify: `addons/erp_telegram_notify/models/__init__.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_server_action.py`

**Interfaces:**
- Consumes: `telegram.outbox._enqueue()` và `_flush_after_commit()` (Task 4), `html_to_telegram()` (Task 2), `telegram.channel` (Task 3)
- Produces:
  - `ir.actions.server.state` nhận thêm giá trị `'telegram'`
  - Field `telegram_channel_id` (Many2one `telegram.channel`), `telegram_template_id` (Many2one `mail.template`), `telegram_content_level` (Selection `link_only`/`full`), `telegram_add_link` (Boolean)
  - `ir.actions.server._telegram_render_body(record) -> str`
  - `ir.actions.server._telegram_reply_markup(record) -> str | None`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_server_action.py`:

```python
import json

from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestTelegramServerAction(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.channel = self.env["telegram.channel"].create({
            "name": "Ops", "bot_id": self.bot.id, "chat_id": "-100777",
        })
        self.partner = self.env["res.partner"].create({"name": "Công ty A & B"})
        self.model_partner = self.env["ir.model"]._get("res.partner")

    def _make_action(self, **overrides):
        values = {
            "name": "Notify Telegram",
            "model_id": self.model_partner.id,
            "state": "telegram",
            "telegram_channel_id": self.channel.id,
        }
        values.update(overrides)
        return self.env["ir.actions.server"].create(values)

    def test_state_telegram_is_selectable(self):
        action = self._make_action()
        self.assertEqual(action.state, "telegram")

    def test_run_enqueues_one_outbox_row_per_record(self):
        other = self.env["res.partner"].create({"name": "Công ty C"})
        action = self._make_action()
        action.with_context(active_model="res.partner",
                            active_ids=[self.partner.id, other.id]).run()
        rows = self.env["telegram.outbox"].search([("res_model", "=", "res.partner")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows.mapped("res_id")), {self.partner.id, other.id})
        self.assertEqual(set(rows.mapped("channel_id")), {self.channel})

    def test_link_only_body_contains_display_name_escaped(self):
        action = self._make_action(telegram_content_level="link_only")
        body = action._telegram_render_body(self.partner)
        self.assertEqual(body, "<b>Công ty A &amp; B</b>")

    def test_full_body_appends_rendered_template(self):
        template = self.env["mail.template"].create({
            "name": "TG body",
            "model_id": self.model_partner.id,
            "body_html": "<p>Đã cập nhật <b>{{ object.name }}</b></p>",
        })
        action = self._make_action(telegram_content_level="full",
                                   telegram_template_id=template.id)
        body = action._telegram_render_body(self.partner)
        self.assertIn("<b>Công ty A &amp; B</b>", body)
        self.assertIn("Đã cập nhật <b>Công ty A &amp; B</b>", body)
        self.assertNotIn("<p>", body)

    def test_full_falls_back_to_header_without_template(self):
        action = self._make_action(telegram_content_level="full")
        self.assertEqual(action._telegram_render_body(self.partner), "<b>Công ty A &amp; B</b>")

    def test_reply_markup_carries_record_deep_link(self):
        action = self._make_action(telegram_add_link=True)
        markup = json.loads(action._telegram_reply_markup(self.partner))
        button = markup["inline_keyboard"][0][0]
        self.assertIn("/mail/view?model=res.partner&res_id=%s" % self.partner.id, button["url"])

    def test_reply_markup_is_none_when_link_disabled(self):
        action = self._make_action(telegram_add_link=False)
        self.assertIsNone(action._telegram_reply_markup(self.partner))

    def test_run_without_channel_is_a_noop(self):
        action = self._make_action(telegram_channel_id=False)
        action.with_context(active_model="res.partner", active_ids=[self.partner.id]).run()
        self.assertFalse(self.env["telegram.outbox"].search([("res_model", "=", "res.partner")]))

    def test_automation_rule_accepts_telegram_action(self):
        action = self._make_action()
        rule = self.env["base.automation"].create({
            "name": "Partner changed",
            "model_id": self.model_partner.id,
            "trigger": "on_create_or_write",
            "action_server_ids": [(4, action.id)],
        })
        self.assertEqual(rule.action_server_ids, action)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `ValueError: Wrong value for ir.actions.server.state: 'telegram'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/models/ir_actions_server.py`:

```python
import json
from html import escape

from odoo import _, fields, models

from ..tools.html2tg import html_to_telegram


class IrActionsServer(models.Model):
    _inherit = "ir.actions.server"

    state = fields.Selection(
        selection_add=[("telegram", "Send Telegram")],
        ondelete={"telegram": "cascade"},
    )
    telegram_channel_id = fields.Many2one(
        "telegram.channel", string="Telegram Channel",
        help="Destination group or topic for this notification.",
    )
    telegram_template_id = fields.Many2one(
        "mail.template", string="Telegram Template",
        domain="[('model_id', '=', model_id)]",
        help="Rendered as the message body when the content level is Full.",
    )
    telegram_content_level = fields.Selection(
        [("link_only", "Link only"), ("full", "Full content")],
        string="Content Level", default="link_only", required=True,
        help="A Telegram group sits outside Odoo's access rules: everyone in the "
             "group reads whatever is relayed. 'Link only' sends the record name "
             "and a button, keeping the data behind Odoo's login.",
    )
    telegram_add_link = fields.Boolean(
        string="Add Record Button", default=True,
        help="Append an inline button that opens the record in Odoo.",
    )

    def _telegram_render_body(self, record):
        """Return the Telegram-safe message body for ``record``."""
        self.ensure_one()
        header = "<b>%s</b>" % escape(record.display_name or "")
        if self.telegram_content_level != "full" or not self.telegram_template_id:
            return html_to_telegram(header)
        rendered = self.telegram_template_id._render_field("body_html", [record.id])[record.id]
        return html_to_telegram("%s<br/>%s" % (header, rendered or ""))

    def _telegram_reply_markup(self, record):
        """Return a serialised inline keyboard, or None when disabled."""
        self.ensure_one()
        if not self.telegram_add_link:
            return None
        url = "%s/mail/view?model=%s&res_id=%s" % (
            record.get_base_url(), record._name, record.id,
        )
        return json.dumps({
            "inline_keyboard": [[{"text": _("Open in Odoo"), "url": url}]]
        })

    def _run_action_telegram_multi(self, eval_context=None):
        """Queue one Telegram message per active record."""
        if not self.telegram_channel_id:
            return False
        res_ids = self.env.context.get("active_ids") or []
        if not res_ids and self.env.context.get("active_id"):
            res_ids = [self.env.context["active_id"]]
        if not res_ids:
            return False
        records = self.env[self.model_name].browse(res_ids).exists()
        outbox = self.env["telegram.outbox"].sudo()
        for record in records:
            outbox._enqueue(
                self.telegram_channel_id,
                self._telegram_render_body(record),
                res_model=record._name,
                res_id=record.id,
                reply_markup=self._telegram_reply_markup(record),
            )
        outbox._flush_after_commit()
        return False
```

Sửa `addons/erp_telegram_notify/models/__init__.py` thành:

```python
from . import telegram_bot
from . import telegram_channel
from . import telegram_outbox
from . import ir_actions_server
```

Sửa `addons/erp_telegram_notify/tests/__init__.py` thành:

```python
from . import test_bot
from . import test_html2tg
from . import test_telegram_api
from . import test_outbox
from . import test_server_action
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 9 tests trong `TestTelegramServerAction` / 9 tests in `TestTelegramServerAction`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add telegram server action type for automation rules"
```

---

## Task 6: Gộp tin trùng trong cửa sổ thời gian
## Task 6: Coalesce duplicate messages within a time window

**Bối cảnh / Context:** Một hợp đồng bị sửa 8 lần trong hai phút sẽ sinh 8 tin, vượt luôn giới hạn 20 tin/phút/group của Telegram và gây nhiễu cho người đọc. Ta gộp: nếu đã có một dòng `pending` cho cùng `(channel, res_model, res_id)` chưa gửi, thì cập nhật nội dung dòng đó thay vì tạo dòng mới.
EN: A contract edited 8 times in two minutes produces 8 messages, blowing through Telegram's 20/minute group cap and drowning the reader. We coalesce: if a `pending` row already exists for the same `(channel, res_model, res_id)`, update it in place instead of creating another.

**Files:**
- Modify: `addons/erp_telegram_notify/models/telegram_outbox.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_debounce.py`

**Interfaces:**
- Consumes: `telegram.outbox._enqueue()` (Task 4)
- Produces: `_enqueue()` nhận thêm tham số `coalesce: bool = True`; hằng số `COALESCE_WINDOW: int` (giây)

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_debounce.py`:

```python
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestOutboxCoalesce(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.channel = self.env["telegram.channel"].create({
            "name": "Ops", "bot_id": self.bot.id, "chat_id": "-100777",
        })
        self.Outbox = self.env["telegram.outbox"]

    def test_second_enqueue_updates_the_pending_row(self):
        first = self.Outbox._enqueue(self.channel, "v1", res_model="res.partner", res_id=1)
        second = self.Outbox._enqueue(self.channel, "v2", res_model="res.partner", res_id=1)
        self.assertEqual(first, second)
        self.assertEqual(first.body, "v2")
        self.assertEqual(
            self.Outbox.search_count([("res_model", "=", "res.partner"), ("res_id", "=", 1)]), 1
        )

    def test_different_records_are_not_coalesced(self):
        self.Outbox._enqueue(self.channel, "a", res_model="res.partner", res_id=1)
        self.Outbox._enqueue(self.channel, "b", res_model="res.partner", res_id=2)
        self.assertEqual(self.Outbox.search_count([("res_model", "=", "res.partner")]), 2)

    def test_sent_rows_are_not_coalesced(self):
        first = self.Outbox._enqueue(self.channel, "a", res_model="res.partner", res_id=1)
        first.state = "sent"
        second = self.Outbox._enqueue(self.channel, "b", res_model="res.partner", res_id=1)
        self.assertNotEqual(first, second)
        self.assertEqual(self.Outbox.search_count([("res_model", "=", "res.partner")]), 2)

    def test_rows_older_than_window_are_not_coalesced(self):
        from odoo.addons.erp_telegram_notify.models.telegram_outbox import COALESCE_WINDOW
        first = self.Outbox._enqueue(self.channel, "a", res_model="res.partner", res_id=1)
        first.create_date = fields.Datetime.now() - timedelta(seconds=COALESCE_WINDOW + 10)
        second = self.Outbox._enqueue(self.channel, "b", res_model="res.partner", res_id=1)
        self.assertNotEqual(first, second)

    def test_rows_without_record_are_never_coalesced(self):
        first = self.Outbox._enqueue(self.channel, "a")
        second = self.Outbox._enqueue(self.channel, "b")
        self.assertNotEqual(first, second)

    def test_coalesce_can_be_disabled(self):
        first = self.Outbox._enqueue(self.channel, "a", res_model="res.partner", res_id=1)
        second = self.Outbox._enqueue(
            self.channel, "b", res_model="res.partner", res_id=1, coalesce=False
        )
        self.assertNotEqual(first, second)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL — `test_second_enqueue_updates_the_pending_row` báo `2 != 1` (mỗi lần gọi vẫn tạo dòng mới / each call still creates a new row)

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Trong `addons/erp_telegram_notify/models/telegram_outbox.py`, thêm hằng số ngay dưới `MAX_RETRY`:

```python
# Messages for the same record queued within this many seconds are merged
# into a single message, so a burst of edits does not flood the group.
COALESCE_WINDOW = 60
```

Thay thế toàn bộ method `_enqueue` bằng:

```python
    @api.model
    def _enqueue(self, channel, body, res_model=None, res_id=None,
                 reply_markup=None, coalesce=True):
        """Queue one message. Safe to call inside a business transaction.

        When ``coalesce`` is set and an unsent message for the same record is
        already queued within ``COALESCE_WINDOW`` seconds, that message is
        updated in place instead of a second one being created.
        """
        if coalesce and res_model and res_id:
            cutoff = fields.Datetime.now() - timedelta(seconds=COALESCE_WINDOW)
            existing = self.search([
                ("channel_id", "=", channel.id),
                ("res_model", "=", res_model),
                ("res_id", "=", res_id),
                ("state", "=", "pending"),
                ("create_date", ">=", cutoff),
            ], limit=1)
            if existing:
                existing.write({"body": body, "reply_markup": reply_markup})
                return existing
        return self.create({
            "channel_id": channel.id,
            "body": body,
            "reply_markup": reply_markup,
            "res_model": res_model,
            "res_id": res_id,
        })
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 6 tests trong `TestOutboxCoalesce`, và toàn bộ test của Task 4, 5 vẫn xanh / 6 tests in `TestOutboxCoalesce`, with Task 4 and 5 tests still green

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): coalesce repeated notifications for the same record"
```

---
## Task 7: Controller webhook nhận update từ Telegram
## Task 7: Inbound webhook controller

**Bối cảnh / Context:** Đây là bề mặt công khai duy nhất của addon, nên bảo mật là trọng tâm. Telegram gửi JSON thuần chứ không phải JSON-RPC, nên controller PHẢI là `type='http'` — dùng `type='jsonrpc'` sẽ hỏng parse. Xác thực bằng header `X-Telegram-Bot-Api-Secret-Token` mà Telegram gửi kèm mọi update, so sánh bằng `secrets.compare_digest` để tránh rò rỉ qua thời gian so sánh.
EN: This is the addon's only public surface, so security is the focus. Telegram posts plain JSON, not JSON-RPC, so the controller MUST be `type='http'`. Authenticate with the `X-Telegram-Bot-Api-Secret-Token` header Telegram attaches to every update, compared with `secrets.compare_digest` to avoid a timing leak.

**Files:**
- Create: `addons/erp_telegram_notify/controllers/__init__.py`
- Create: `addons/erp_telegram_notify/controllers/webhook.py`
- Modify: `addons/erp_telegram_notify/__init__.py`
- Modify: `addons/erp_telegram_notify/models/telegram_bot.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_webhook.py`

**Interfaces:**
- Consumes: `telegram.bot` (Task 1), `telegram_api.call()` (Task 3)
- Produces:
  - Route `POST /telegram/webhook/<int:bot_id>`
  - `telegram.bot._process_update(payload: dict) -> None` — điểm phân phối cho mọi loại update
  - `telegram.bot.action_set_webhook() -> None`, `telegram.bot.action_delete_webhook() -> None`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_webhook.py`:

```python
import json
from unittest.mock import patch

from odoo.tests.common import HttpCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestTelegramWebhook(HttpCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.url = "/telegram/webhook/%s" % self.bot.id

    def _post(self, payload, secret):
        return self.url_open(
            self.url,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": secret,
            },
        )

    def test_rejects_wrong_secret(self):
        with patch.object(type(self.env["telegram.bot"]), "_process_update") as proc:
            response = self._post({"update_id": 1}, "wrong-secret")
        self.assertEqual(response.status_code, 403)
        proc.assert_not_called()

    def test_rejects_missing_secret(self):
        response = self.url_open(
            self.url, data=json.dumps({"update_id": 1}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 403)

    def test_rejects_unknown_bot(self):
        response = self.url_open(
            "/telegram/webhook/999999", data=json.dumps({"update_id": 1}),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "x"},
        )
        self.assertEqual(response.status_code, 403)

    def test_accepts_valid_update(self):
        secret = self.bot.sudo().webhook_secret
        with patch.object(type(self.env["telegram.bot"]), "_process_update") as proc:
            response = self._post({"update_id": 1, "message": {"text": "hi"}}, secret)
        self.assertEqual(response.status_code, 200)
        proc.assert_called_once()

    def test_returns_200_even_when_processing_raises(self):
        """Telegram retries on non-2xx; a bug must not create a retry storm."""
        secret = self.bot.sudo().webhook_secret
        with patch.object(
            type(self.env["telegram.bot"]), "_process_update",
            side_effect=ValueError("bug"),
        ):
            response = self._post({"update_id": 1}, secret)
        self.assertEqual(response.status_code, 200)

    def test_returns_400_on_malformed_json(self):
        secret = self.bot.sudo().webhook_secret
        response = self.url_open(
            self.url, data="not json{",
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": secret},
        )
        self.assertEqual(response.status_code, 400)


@tagged("post_install", "-at_install")
class TestWebhookRegistration(HttpCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})

    def test_set_webhook_sends_url_and_secret(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot.action_set_webhook()
        self.assertEqual(call.call_args.args[1], "setWebhook")
        payload = call.call_args.args[2]
        self.assertTrue(payload["url"].endswith("/telegram/webhook/%s" % self.bot.id))
        self.assertEqual(payload["secret_token"], self.bot.sudo().webhook_secret)

    def test_delete_webhook_calls_api(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot.action_delete_webhook()
        self.assertEqual(call.call_args.args[1], "deleteWebhook")
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `404` cho mọi request tới `/telegram/webhook/...` và `AttributeError: 'telegram.bot' object has no attribute 'action_set_webhook'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/controllers/__init__.py`:

```python
from . import webhook
```

Tạo `addons/erp_telegram_notify/controllers/webhook.py`:

```python
import json
import logging
import secrets

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramWebhook(http.Controller):

    @http.route(
        "/telegram/webhook/<int:bot_id>",
        type="http", auth="public", methods=["POST"],
        csrf=False, save_session=False,
    )
    def telegram_webhook(self, bot_id, **kwargs):
        """Receive one Telegram update.

        Always answers 2xx once authenticated: Telegram retries non-2xx
        responses, so an internal bug must not turn into a retry storm.
        """
        presented = request.httprequest.headers.get(SECRET_HEADER) or ""
        bot = request.env["telegram.bot"].sudo().browse(bot_id).exists()
        expected = bot.webhook_secret or "" if bot else ""
        if not expected or not secrets.compare_digest(presented, expected):
            _logger.warning("Rejected Telegram webhook for bot %s: bad secret", bot_id)
            return request.make_response("", status=403)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True))
        except ValueError:
            return request.make_response("", status=400)

        try:
            bot._process_update(payload)
        except Exception:  # noqa: BLE001 - see docstring
            _logger.exception("Failed to process Telegram update for bot %s", bot_id)

        return request.make_response("", status=200)
```

Sửa `addons/erp_telegram_notify/__init__.py` thành:

```python
from . import controllers
from . import models
from . import tools
```

Thêm vào cuối class `TelegramBot` trong `addons/erp_telegram_notify/models/telegram_bot.py`:

```python
    def _webhook_url(self):
        self.ensure_one()
        return "%s/telegram/webhook/%s" % (self.get_base_url(), self.id)

    def action_set_webhook(self):
        """Register this Odoo instance as the bot's webhook endpoint."""
        for bot in self:
            telegram_api.call(bot.sudo().token, "setWebhook", {
                "url": bot._webhook_url(),
                "secret_token": bot.sudo().webhook_secret,
                "allowed_updates": ["message", "callback_query", "my_chat_member"],
            })

    def action_delete_webhook(self):
        """Stop Telegram from delivering updates to this instance."""
        for bot in self:
            telegram_api.call(bot.sudo().token, "deleteWebhook", {})

    def _process_update(self, payload):
        """Dispatch one Telegram update. Extended by later tasks."""
        self.ensure_one()
        return False
```

Và thêm import ở đầu file `telegram_bot.py`, ngay dưới `from odoo import api, fields, models`:

```python
from ..tools import telegram_api
```

Sửa `addons/erp_telegram_notify/tests/__init__.py` thành:

```python
from . import test_bot
from . import test_html2tg
from . import test_telegram_api
from . import test_outbox
from . import test_server_action
from . import test_debounce
from . import test_webhook
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 8 tests mới / 8 new tests

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add authenticated inbound webhook controller"
```

---

## Task 8: Lệnh `/register` tự tạo kênh
## Task 8: `/register` command auto-creates a channel

**Bối cảnh / Context:** Bắt admin tự chạy `getUpdates` rồi copy một `chat_id` âm là công thức chắc chắn sinh ticket hỗ trợ. Thay vào đó, ai đó gõ `/register` trong group, bot tự tạo bản ghi `telegram.channel` với đúng `chat_id` và `thread_id`. Bản ghi tạo ra ở trạng thái `pending` — một group lạ tự đăng ký sẽ KHÔNG nhận được tin cho tới khi admin Odoo xác nhận.
EN: Making an admin run `getUpdates` and copy a negative `chat_id` guarantees support tickets. Instead, someone types `/register` in the group and the bot creates the `telegram.channel` record with the right `chat_id` and `thread_id`. It lands in `pending` state — a stranger's group that self-registers receives nothing until an Odoo administrator confirms it.

**Files:**
- Modify: `addons/erp_telegram_notify/models/telegram_bot.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_register_command.py`

**Interfaces:**
- Consumes: `telegram.bot._process_update()` (Task 7), `telegram.channel` (Task 3), `telegram_api.call()` (Task 3)
- Produces: `telegram.bot._handle_message(message: dict) -> None`, `telegram.bot._reply(chat_id, thread_id, text) -> None`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_register_command.py`:

```python
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestRegisterCommand(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.Channel = self.env["telegram.channel"]

    def _update(self, text, chat_id=-1001234567890, thread_id=None, title="Phòng Kế toán"):
        message = {
            "message_id": 1,
            "chat": {"id": chat_id, "title": title, "type": "supergroup"},
            "text": text,
        }
        if thread_id:
            message["message_thread_id"] = thread_id
        return {"update_id": 1, "message": message}

    def test_register_creates_pending_channel(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._update("/register"))
        channel = self.Channel.search([("chat_id", "=", "-1001234567890")])
        self.assertEqual(len(channel), 1)
        self.assertEqual(channel.state, "pending")
        self.assertEqual(channel.name, "Phòng Kế toán")
        self.assertEqual(channel.bot_id, self.bot)

    def test_register_stores_topic_id(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._update("/register", thread_id=77))
        channel = self.Channel.search([("chat_id", "=", "-1001234567890")])
        self.assertEqual(channel.thread_id, 77)

    def test_register_replies_in_the_same_thread(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}) as call:
            self.bot._process_update(self._update("/register", thread_id=77))
        payload = call.call_args.args[2]
        self.assertEqual(payload["chat_id"], "-1001234567890")
        self.assertEqual(payload["message_thread_id"], 77)

    def test_register_is_idempotent(self):
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._update("/register"))
            self.bot._process_update(self._update("/register"))
        self.assertEqual(self.Channel.search_count([("chat_id", "=", "-1001234567890")]), 1)

    def test_register_does_not_reactivate_a_confirmed_channel(self):
        existing = self.Channel.create({
            "name": "Kế toán", "bot_id": self.bot.id,
            "chat_id": "-1001234567890", "state": "confirmed",
        })
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._update("/register"))
        self.assertEqual(existing.state, "confirmed")

    def test_command_with_bot_mention_is_accepted(self):
        self.bot.bot_username = "erp_bot"
        with patch.object(telegram_api, "call", return_value={"message_id": 2}):
            self.bot._process_update(self._update("/register@erp_bot"))
        self.assertEqual(self.Channel.search_count([("chat_id", "=", "-1001234567890")]), 1)

    def test_unknown_command_creates_nothing(self):
        with patch.object(telegram_api, "call") as call:
            self.bot._process_update(self._update("/somethingelse"))
        call.assert_not_called()
        self.assertEqual(self.Channel.search_count([]), 0)

    def test_plain_text_is_ignored(self):
        with patch.object(telegram_api, "call") as call:
            self.bot._process_update(self._update("chào cả nhà"))
        call.assert_not_called()
        self.assertEqual(self.Channel.search_count([]), 0)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL — `test_register_creates_pending_channel` báo `0 != 1` (`_process_update` hiện chỉ `return False` / `_process_update` currently just returns False)

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Trong `addons/erp_telegram_notify/models/telegram_bot.py`, thay thế method `_process_update` bằng:

```python
    def _process_update(self, payload):
        """Dispatch one Telegram update to the right handler."""
        self.ensure_one()
        if payload.get("message"):
            return self._handle_message(payload["message"])
        return False

    def _reply(self, chat_id, thread_id, text):
        """Send a plain reply back into the originating chat and topic."""
        self.ensure_one()
        message = {"chat_id": str(chat_id), "text": text, "parse_mode": "HTML"}
        if thread_id:
            message["message_thread_id"] = thread_id
        telegram_api.call(self.sudo().token, "sendMessage", message)

    def _command_name(self, text):
        """Return the bare command in ``text``, or False.

        Telegram appends ``@bot_username`` when several bots share a group.
        """
        if not text or not text.startswith("/"):
            return False
        word = text.split(maxsplit=1)[0]
        return word[1:].split("@", 1)[0].lower()

    def _handle_message(self, message):
        """Handle an incoming chat message."""
        self.ensure_one()
        if self._command_name(message.get("text")) != "register":
            return False

        chat = message.get("chat") or {}
        chat_id = str(chat.get("id"))
        thread_id = message.get("message_thread_id") or 0
        Channel = self.env["telegram.channel"].sudo()
        existing = Channel.with_context(active_test=False).search([
            ("bot_id", "=", self.id),
            ("chat_id", "=", chat_id),
            ("thread_id", "=", thread_id),
        ], limit=1)
        if existing:
            self._reply(chat_id, thread_id, _(
                "This chat is already registered as “%s” (%s).",
                existing.name, existing.state,
            ))
            return False

        channel = Channel.create({
            "name": chat.get("title") or chat_id,
            "bot_id": self.id,
            "chat_id": chat_id,
            "thread_id": thread_id,
            "state": "pending",
        })
        self._reply(chat_id, thread_id, _(
            "✅ Registered as “%s”. An Odoo administrator must confirm this "
            "channel before notifications start arriving.",
            channel.name,
        ))
        return True
```

Sửa dòng import đầu file `telegram_bot.py` thành:

```python
from odoo import _, api, fields, models
```

Sửa `addons/erp_telegram_notify/tests/__init__.py`, thêm dòng cuối:

```python
from . import test_register_command
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 8 tests trong `TestRegisterCommand` / 8 tests in `TestRegisterCommand`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): auto-register channels via the /register command"
```

---
## Task 9: Nút inline duyệt/từ chối, có allowlist method
## Task 9: Inline approve/reject buttons with a method allowlist

**Bối cảnh / Context:** Đây là tính năng đắt giá nhất của module — sếp duyệt đơn nghỉ ngay trong Telegram, không cần mở ERP. Nó cũng là chỗ nguy hiểm nhất: nếu `callback_data` chứa thẳng tên method thì bất kỳ ai đoán được định dạng đều gọi được method tuỳ ý trên server. Hai lớp phòng vệ bắt buộc:
1. `callback_data` chỉ chứa **id của một bản ghi `telegram.button`** đã được admin khai báo trước — tên method không bao giờ đi qua đường truyền.
2. Method chạy dưới `with_user(odoo_user)` nên **ACL và record rule của Odoo áp dụng nguyên vẹn**. Người Telegram chưa được map sang user Odoo thì không làm được gì.

EN: This is the module's highest-value feature — approving a leave request straight from Telegram. It is also the most dangerous: if `callback_data` carried a method name, anyone who guessed the format could invoke arbitrary methods server-side. Two mandatory defences: (1) `callback_data` carries only the id of an admin-declared `telegram.button` record, so a method name never travels over the wire; (2) the method runs under `with_user(odoo_user)` so Odoo's ACLs and record rules apply in full, and an unmapped Telegram user can do nothing.

**Files:**
- Create: `addons/erp_telegram_notify/models/telegram_button.py`
- Create: `addons/erp_telegram_notify/models/res_users.py`
- Modify: `addons/erp_telegram_notify/models/__init__.py`
- Modify: `addons/erp_telegram_notify/models/telegram_bot.py`
- Modify: `addons/erp_telegram_notify/models/ir_actions_server.py`
- Modify: `addons/erp_telegram_notify/security/ir.model.access.csv`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_buttons.py`

**Interfaces:**
- Consumes: `telegram.bot._process_update()` (Task 7), `_reply()` (Task 8), `ir.actions.server._telegram_reply_markup()` (Task 5)
- Produces:
  - Model `telegram.button`: `name` (Char), `model_id` (Many2one `ir.model`), `method` (Char), `sequence` (Integer)
  - Field `res.users.telegram_user_id` (Char, unique)
  - `telegram.bot._handle_callback_query(callback: dict) -> None`
  - Field `ir.actions.server.telegram_button_ids` (Many2many `telegram.button`)

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_buttons.py`:

```python
import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestTelegramButton(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.model_partner = self.env["ir.model"]._get("res.partner")
        self.partner = self.env["res.partner"].create({"name": "Khách A"})
        self.button = self.env["telegram.button"].create({
            "name": "Toggle",
            "model_id": self.model_partner.id,
            "method": "toggle_active",
        })
        self.user = new_test_user(
            self.env, login="tg_approver", groups="base.group_user,base.group_partner_manager"
        )
        self.user.telegram_user_id = "555001"

    def _callback(self, data, from_id="555001"):
        return {
            "update_id": 2,
            "callback_query": {
                "id": "cbq-1",
                "from": {"id": int(from_id)},
                "data": data,
                "message": {"message_id": 9, "chat": {"id": -100777}},
            },
        }

    # --- Allowlist integrity -------------------------------------------------

    def test_private_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["telegram.button"].create({
                "name": "Bad", "model_id": self.model_partner.id, "method": "_write",
            })

    def test_unknown_method_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["telegram.button"].create({
                "name": "Bad", "model_id": self.model_partner.id, "method": "no_such_method",
            })

    # --- Callback dispatch ---------------------------------------------------

    def test_callback_runs_the_method_as_the_mapped_user(self):
        self.assertTrue(self.partner.active)
        with patch.object(telegram_api, "call", return_value=True):
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id))
            )
        self.assertFalse(self.partner.active)

    def test_callback_from_unmapped_telegram_user_is_refused(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id),
                               from_id="999999")
            )
        self.assertTrue(self.partner.active, "record must be untouched")
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")
        self.assertTrue(call.call_args.args[2]["show_alert"])

    def test_callback_respects_odoo_access_rights(self):
        reader = new_test_user(self.env, login="tg_reader2", groups="base.group_user")
        reader.telegram_user_id = "555002"
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(
                self._callback("tgb:%s:%s" % (self.button.id, self.partner.id),
                               from_id="555002")
            )
        self.assertTrue(self.partner.active, "AccessError must block the write")
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_callback_with_unknown_button_id_is_ignored(self):
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(self._callback("tgb:999999:%s" % self.partner.id))
        self.assertTrue(self.partner.active)
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_callback_with_malformed_data_is_ignored(self):
        with patch.object(telegram_api, "call", return_value=True):
            self.bot._process_update(self._callback("garbage"))
        self.assertTrue(self.partner.active)

    def test_callback_on_deleted_record_is_ignored(self):
        res_id = self.partner.id
        self.partner.unlink()
        with patch.object(telegram_api, "call", return_value=True) as call:
            self.bot._process_update(self._callback("tgb:%s:%s" % (self.button.id, res_id)))
        self.assertEqual(call.call_args.args[1], "answerCallbackQuery")

    def test_telegram_user_id_is_unique(self):
        other = new_test_user(self.env, login="tg_dup", groups="base.group_user")
        with self.assertRaises(Exception):
            other.telegram_user_id = "555001"
            other.flush_recordset()

    # --- Markup rendering ----------------------------------------------------

    def test_action_markup_includes_declared_buttons(self):
        action = self.env["ir.actions.server"].create({
            "name": "Notify",
            "model_id": self.model_partner.id,
            "state": "telegram",
            "telegram_channel_id": self.env["telegram.channel"].create({
                "name": "Ops", "bot_id": self.bot.id, "chat_id": "-100777",
            }).id,
            "telegram_button_ids": [(4, self.button.id)],
        })
        markup = json.loads(action._telegram_reply_markup(self.partner))
        rows = markup["inline_keyboard"]
        callbacks = [b for row in rows for b in row if "callback_data" in b]
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0]["text"], "Toggle")
        self.assertEqual(
            callbacks[0]["callback_data"], "tgb:%s:%s" % (self.button.id, self.partner.id)
        )
        self.assertLessEqual(len(callbacks[0]["callback_data"].encode()), 64)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `KeyError: 'telegram.button'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Tạo `addons/erp_telegram_notify/models/telegram_button.py`:

```python
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TelegramButton(models.Model):
    """Allowlist of methods that may be invoked from a Telegram inline button.

    Nothing outside this table is callable: the callback payload carries only a
    record id from here, never a method name.
    """

    _name = "telegram.button"
    _description = "Telegram Inline Button"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Label shown on the button.")
    sequence = fields.Integer(default=10)
    model_id = fields.Many2one("ir.model", required=True, ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True)
    method = fields.Char(
        required=True,
        help="Public method invoked on the record, e.g. action_approve. "
             "Runs as the Odoo user mapped to the Telegram sender, so access "
             "rights and record rules still apply.",
    )

    @api.constrains("model_id", "method")
    def _check_method_is_callable(self):
        for button in self:
            method = (button.method or "").strip()
            if not method or method.startswith("_"):
                raise ValidationError(
                    _("Method %(method)s is not allowed: only public methods "
                      "may be bound to a Telegram button.", method=button.method)
                )
            model = self.env.get(button.model_id.model)
            if model is None or not callable(getattr(model, method, None)):
                raise ValidationError(
                    _("Model %(model)s has no callable method %(method)s.",
                      model=button.model_id.model, method=method)
                )
```

Tạo `addons/erp_telegram_notify/models/res_users.py`:

```python
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    telegram_user_id = fields.Char(
        string="Telegram User ID",
        copy=False, index=True,
        help="Numeric Telegram id of this user. Required before they can act "
             "on inline buttons.",
    )

    _telegram_user_uniq = models.Constraint(
        "UNIQUE(telegram_user_id)",
        "That Telegram user is already linked to another Odoo user.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ["telegram_user_id"]
```

Sửa `addons/erp_telegram_notify/models/__init__.py` thành:

```python
from . import telegram_bot
from . import telegram_channel
from . import telegram_outbox
from . import telegram_button
from . import res_users
from . import ir_actions_server
```

Trong `addons/erp_telegram_notify/models/telegram_bot.py`, thay method `_process_update` bằng:

```python
    def _process_update(self, payload):
        """Dispatch one Telegram update to the right handler."""
        self.ensure_one()
        if payload.get("message"):
            return self._handle_message(payload["message"])
        if payload.get("callback_query"):
            return self._handle_callback_query(payload["callback_query"])
        return False
```

Và thêm vào cuối class `TelegramBot`:

```python
    def _answer_callback(self, callback_id, text, alert=False):
        telegram_api.call(self.sudo().token, "answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": alert,
        })

    def _handle_callback_query(self, callback):
        """Run the method behind an inline button, as the mapped Odoo user."""
        self.ensure_one()
        callback_id = callback.get("id")
        parts = (callback.get("data") or "").split(":")
        if len(parts) != 3 or parts[0] != "tgb":
            return False

        button = self.env["telegram.button"].sudo().browse(int(parts[1])
                                                           if parts[1].isdigit() else 0).exists()
        if not button:
            self._answer_callback(callback_id, _("This button no longer exists."), alert=True)
            return False

        sender_id = str((callback.get("from") or {}).get("id") or "")
        user = self.env["res.users"].sudo().search(
            [("telegram_user_id", "=", sender_id)], limit=1
        )
        if not user:
            self._answer_callback(callback_id, _(
                "Your Telegram account is not linked to an Odoo user. "
                "Ask an administrator to link it before using this button."
            ), alert=True)
            return False

        record = self.env[button.model_name].sudo().browse(
            int(parts[2]) if parts[2].isdigit() else 0
        ).exists()
        if not record:
            self._answer_callback(callback_id, _("This record no longer exists."), alert=True)
            return False

        try:
            getattr(record.with_user(user), button.method)()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            self.env.cr.rollback()
            self._answer_callback(callback_id, _("Refused: %s", exc), alert=True)
            return False

        self._answer_callback(callback_id, _("✅ %s done.", button.name))
        return True
```

Trong `addons/erp_telegram_notify/models/ir_actions_server.py`, thêm field vào class `IrActionsServer`:

```python
    telegram_button_ids = fields.Many2many(
        "telegram.button", string="Action Buttons",
        domain="[('model_id', '=', model_id)]",
        help="Inline buttons appended to the message. Each one runs its "
             "declared method as the Odoo user mapped to the Telegram sender.",
    )
```

Và thay method `_telegram_reply_markup` bằng:

```python
    def _telegram_reply_markup(self, record):
        """Return a serialised inline keyboard, or None when there is nothing to show."""
        self.ensure_one()
        rows = []
        if self.telegram_add_link:
            url = "%s/mail/view?model=%s&res_id=%s" % (
                record.get_base_url(), record._name, record.id,
            )
            rows.append([{"text": _("Open in Odoo"), "url": url}])
        action_row = [
            {
                "text": button.name,
                # callback_data is capped at 64 bytes by Telegram; ids keep it short
                # and keep the method name off the wire.
                "callback_data": "tgb:%s:%s" % (button.id, record.id),
            }
            for button in self.telegram_button_ids
        ]
        if action_row:
            rows.append(action_row)
        if not rows:
            return None
        return json.dumps({"inline_keyboard": rows})
```

Thêm dòng vào `addons/erp_telegram_notify/security/ir.model.access.csv`:

```csv
access_telegram_button_user,telegram.button.user,model_telegram_button,base.group_user,1,0,0,0
access_telegram_button_system,telegram.button.system,model_telegram_button,base.group_system,1,1,1,1
```

Sửa `addons/erp_telegram_notify/tests/__init__.py`, thêm dòng cuối:

```python
from . import test_buttons
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 10 tests trong `TestTelegramButton` / 10 tests in `TestTelegramButton`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add inline action buttons with a method allowlist"
```

---

## Task 10: Giao diện quản trị và menu
## Task 10: Admin views and menus

**Bối cảnh / Context:** Đến đây toàn bộ logic đã chạy nhưng admin chưa có màn hình nào để cấu hình bot, xác nhận kênh `pending` do `/register` tạo ra, hay soi outbox khi tin không tới. Task này biến module từ "chạy được" thành "vận hành được".
EN: Everything works by now but an administrator has no screen to configure a bot, confirm the `pending` channels `/register` created, or inspect the outbox when a message fails to arrive. This task turns the module from "working" into "operable".

**Files:**
- Create: `addons/erp_telegram_notify/views/telegram_bot_views.xml`
- Create: `addons/erp_telegram_notify/views/telegram_channel_views.xml`
- Create: `addons/erp_telegram_notify/views/telegram_outbox_views.xml`
- Create: `addons/erp_telegram_notify/views/telegram_button_views.xml`
- Create: `addons/erp_telegram_notify/views/ir_actions_server_views.xml`
- Create: `addons/erp_telegram_notify/views/menus.xml`
- Modify: `addons/erp_telegram_notify/models/telegram_channel.py`
- Modify: `addons/erp_telegram_notify/__manifest__.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_views.py`

**Interfaces:**
- Consumes: mọi model từ Task 1–9 / every model from Tasks 1–9
- Produces:
  - `telegram.channel.action_confirm() -> None`
  - Các xmlid: `erp_telegram_notify.action_telegram_bot`, `action_telegram_channel`, `action_telegram_outbox`, `action_telegram_button`, `menu_telegram_root`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_views.py`:

```python
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestTelegramViews(TransactionCase):

    def test_actions_and_menu_exist(self):
        for xmlid in (
            "erp_telegram_notify.action_telegram_bot",
            "erp_telegram_notify.action_telegram_channel",
            "erp_telegram_notify.action_telegram_outbox",
            "erp_telegram_notify.action_telegram_button",
            "erp_telegram_notify.menu_telegram_root",
        ):
            self.assertTrue(self.env.ref(xmlid), "%s is missing" % xmlid)

    def test_form_views_render(self):
        """get_views raises if a view references a field that does not exist."""
        for model in ("telegram.bot", "telegram.channel", "telegram.outbox", "telegram.button"):
            self.env[model].get_views([(None, "form"), (None, "list")])

    def test_server_action_form_exposes_telegram_fields(self):
        arch = self.env["ir.actions.server"].get_views([(None, "form")])["views"]["form"]["arch"]
        self.assertIn("telegram_channel_id", arch)
        self.assertIn("telegram_content_level", arch)

    def test_confirm_moves_channel_to_confirmed(self):
        bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        channel = self.env["telegram.channel"].create({
            "name": "Kế toán", "bot_id": bot.id, "chat_id": "-100777", "state": "pending",
        })
        channel.action_confirm()
        self.assertEqual(channel.state, "confirmed")
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `ValueError: External ID not found in the system: erp_telegram_notify.action_telegram_bot`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Thêm vào cuối class `TelegramChannel` trong `addons/erp_telegram_notify/models/telegram_channel.py`:

```python
    def action_confirm(self):
        """Approve a channel created by the /register command."""
        self.write({"state": "confirmed"})
```

Tạo `addons/erp_telegram_notify/views/telegram_bot_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_telegram_bot_form" model="ir.ui.view">
        <field name="name">telegram.bot.form</field>
        <field name="model">telegram.bot</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_set_webhook" type="object" string="Set Webhook" class="btn-primary"/>
                    <button name="action_delete_webhook" type="object" string="Delete Webhook"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" placeholder="ERP Bot"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="bot_username" placeholder="erp_notify_bot"/>
                            <field name="token" password="True"/>
                            <field name="webhook_secret" password="True"/>
                        </group>
                        <group>
                            <field name="enabled"/>
                            <field name="active" invisible="1"/>
                            <field name="sequence"/>
                        </group>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="view_telegram_bot_list" model="ir.ui.view">
        <field name="name">telegram.bot.list</field>
        <field name="model">telegram.bot</field>
        <field name="arch" type="xml">
            <list>
                <field name="sequence" widget="handle"/>
                <field name="name"/>
                <field name="bot_username"/>
                <field name="enabled"/>
            </list>
        </field>
    </record>

    <record id="action_telegram_bot" model="ir.actions.act_window">
        <field name="name">Telegram Bots</field>
        <field name="res_model">telegram.bot</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

Tạo `addons/erp_telegram_notify/views/telegram_channel_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_telegram_channel_form" model="ir.ui.view">
        <field name="name">telegram.channel.form</field>
        <field name="model">telegram.channel</field>
        <field name="arch" type="xml">
            <form>
                <header>
                    <button name="action_confirm" type="object" string="Confirm"
                            class="btn-primary" invisible="state == 'confirmed'"/>
                    <button name="action_send_test" type="object" string="Send Test Message"/>
                    <field name="state" widget="statusbar" statusbar_visible="pending,confirmed"/>
                </header>
                <sheet>
                    <div class="oe_title">
                        <h1><field name="name" placeholder="Phòng Kế toán"/></h1>
                    </div>
                    <group>
                        <group>
                            <field name="bot_id"/>
                            <field name="chat_id" placeholder="-1001234567890"/>
                            <field name="thread_id"/>
                        </group>
                        <group>
                            <field name="active" invisible="1"/>
                        </group>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="view_telegram_channel_list" model="ir.ui.view">
        <field name="name">telegram.channel.list</field>
        <field name="model">telegram.channel</field>
        <field name="arch" type="xml">
            <list decoration-warning="state == 'pending'">
                <field name="name"/>
                <field name="bot_id"/>
                <field name="chat_id"/>
                <field name="thread_id"/>
                <field name="state"/>
            </list>
        </field>
    </record>

    <record id="action_telegram_channel" model="ir.actions.act_window">
        <field name="name">Telegram Channels</field>
        <field name="res_model">telegram.channel</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

Tạo `addons/erp_telegram_notify/views/telegram_outbox_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_telegram_outbox_list" model="ir.ui.view">
        <field name="name">telegram.outbox.list</field>
        <field name="model">telegram.outbox</field>
        <field name="arch" type="xml">
            <list decoration-danger="state == 'failed'" decoration-muted="state == 'sent'">
                <field name="create_date"/>
                <field name="channel_id"/>
                <field name="res_model"/>
                <field name="res_id"/>
                <field name="state"/>
                <field name="retry_count"/>
                <field name="next_retry_at"/>
                <field name="last_error"/>
            </list>
        </field>
    </record>

    <record id="view_telegram_outbox_form" model="ir.ui.view">
        <field name="name">telegram.outbox.form</field>
        <field name="model">telegram.outbox</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <group>
                        <group>
                            <field name="channel_id"/>
                            <field name="res_model"/>
                            <field name="res_id"/>
                            <field name="telegram_message_id"/>
                        </group>
                        <group>
                            <field name="state"/>
                            <field name="retry_count"/>
                            <field name="next_retry_at"/>
                        </group>
                    </group>
                    <field name="body"/>
                    <field name="reply_markup"/>
                    <field name="last_error"/>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_telegram_outbox" model="ir.actions.act_window">
        <field name="name">Telegram Outbox</field>
        <field name="res_model">telegram.outbox</field>
        <field name="view_mode">list,form</field>
        <field name="context">{'search_default_group_state': 1}</field>
    </record>
</odoo>
```

Tạo `addons/erp_telegram_notify/views/telegram_button_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_telegram_button_list" model="ir.ui.view">
        <field name="name">telegram.button.list</field>
        <field name="model">telegram.button</field>
        <field name="arch" type="xml">
            <list editable="bottom">
                <field name="sequence" widget="handle"/>
                <field name="name"/>
                <field name="model_id"/>
                <field name="method"/>
            </list>
        </field>
    </record>

    <record id="view_telegram_button_form" model="ir.ui.view">
        <field name="name">telegram.button.form</field>
        <field name="model">telegram.button</field>
        <field name="arch" type="xml">
            <form>
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="model_id"/>
                        <field name="model_name" invisible="1"/>
                        <field name="method"/>
                        <field name="sequence"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_telegram_button" model="ir.actions.act_window">
        <field name="name">Telegram Buttons</field>
        <field name="res_model">telegram.button</field>
        <field name="view_mode">list,form</field>
    </record>
</odoo>
```

Tạo `addons/erp_telegram_notify/views/ir_actions_server_views.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_server_action_form_telegram" model="ir.ui.view">
        <field name="name">ir.actions.server.form.telegram</field>
        <field name="model">ir.actions.server</field>
        <field name="inherit_id" ref="base.view_server_action_form"/>
        <field name="arch" type="xml">
            <xpath expr="//field[@name='state']" position="after">
                <field name="telegram_channel_id" invisible="state != 'telegram'"
                       required="state == 'telegram'"/>
                <field name="telegram_content_level" invisible="state != 'telegram'"/>
                <field name="telegram_template_id" invisible="state != 'telegram'"/>
                <field name="telegram_add_link" invisible="state != 'telegram'"/>
                <field name="telegram_button_ids" widget="many2many_tags"
                       invisible="state != 'telegram'"/>
            </xpath>
        </field>
    </record>
</odoo>
```

Tạo `addons/erp_telegram_notify/views/menus.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <menuitem id="menu_telegram_root" name="Telegram"
              parent="base.menu_administration" sequence="90"
              groups="base.group_system"/>
    <menuitem id="menu_telegram_bot" name="Bots"
              parent="menu_telegram_root" action="action_telegram_bot" sequence="10"/>
    <menuitem id="menu_telegram_channel" name="Channels"
              parent="menu_telegram_root" action="action_telegram_channel" sequence="20"/>
    <menuitem id="menu_telegram_button" name="Action Buttons"
              parent="menu_telegram_root" action="action_telegram_button" sequence="30"/>
    <menuitem id="menu_telegram_outbox" name="Outbox"
              parent="menu_telegram_root" action="action_telegram_outbox" sequence="40"/>
</odoo>
```

Sửa khoá `data` trong `addons/erp_telegram_notify/__manifest__.py` thành:

```python
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/telegram_bot_views.xml",
        "views/telegram_channel_views.xml",
        "views/telegram_button_views.xml",
        "views/telegram_outbox_views.xml",
        "views/ir_actions_server_views.xml",
        "views/menus.xml",
    ],
```

Sửa `addons/erp_telegram_notify/tests/__init__.py`, thêm dòng cuối:

```python
from . import test_views
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — toàn bộ suite xanh, 4 tests trong `TestTelegramViews` / whole suite green, 4 tests in `TestTelegramViews`

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): add admin views, menus and channel confirmation"
```

---

## Task 11: Giới hạn tốc độ theo từng kênh
## Task 11: Per-channel rate limiting

**Bối cảnh / Context:** Task 6 gộp các tin trùng của **cùng một record**, nhưng không chặn được tình huống 40 record khác nhau cùng đổi trong một phút — outbox sẽ bắn cả 40 tin vào một group và vượt trần 20 tin/phút của Telegram, kéo theo `429` và cấm tạm thời. Ta đếm số tin đã gửi vào mỗi kênh trong 60 giây gần nhất và dừng lại ở ngưỡng an toàn; phần còn lại nằm nguyên `pending` và cron phút sau đẩy tiếp.
EN: Task 6 merges repeats for the *same* record, but does not cover 40 different records changing within a minute — the outbox would fire all 40 into one group, breach Telegram's 20/minute cap, and earn a `429` plus a temporary ban. We count what each channel has sent in the last 60 seconds, stop at a safe threshold, and leave the rest `pending` for the next cron pass.

**Files:**
- Modify: `addons/erp_telegram_notify/models/telegram_outbox.py`
- Modify: `addons/erp_telegram_notify/tests/__init__.py`
- Test: `addons/erp_telegram_notify/tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `telegram.outbox._flush()` (Task 4)
- Produces: field `telegram.outbox.sent_at` (Datetime); hằng số `RATE_LIMIT_PER_MINUTE: int`

- [ ] **Bước 1: Viết test cho trường hợp thất bại / Write the failing test**

Tạo `addons/erp_telegram_notify/tests/test_rate_limit.py`:

```python
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from odoo.addons.erp_telegram_notify.models.telegram_outbox import RATE_LIMIT_PER_MINUTE
from odoo.addons.erp_telegram_notify.tools import telegram_api


@tagged("post_install", "-at_install")
class TestOutboxRateLimit(TransactionCase):

    def setUp(self):
        super().setUp()
        self.bot = self.env["telegram.bot"].create({"name": "Bot", "token": "1:AA"})
        self.channel = self.env["telegram.channel"].create({
            "name": "Ops", "bot_id": self.bot.id, "chat_id": "-100777",
        })
        self.other = self.env["telegram.channel"].create({
            "name": "HR", "bot_id": self.bot.id, "chat_id": "-100888",
        })
        self.Outbox = self.env["telegram.outbox"]

    def _queue(self, channel, count):
        for index in range(count):
            self.Outbox._enqueue(channel, "msg %s" % index, coalesce=False)

    def test_sent_at_is_stamped(self):
        self._queue(self.channel, 1)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}):
            self.Outbox._flush()
        row = self.Outbox.search([("channel_id", "=", self.channel.id)])
        self.assertTrue(row.sent_at)

    def test_stops_at_the_per_minute_cap(self):
        self._queue(self.channel, RATE_LIMIT_PER_MINUTE + 5)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE)
        self.assertEqual(
            self.Outbox.search_count([("channel_id", "=", self.channel.id),
                                      ("state", "=", "pending")]),
            5,
        )

    def test_cap_is_counted_per_channel_not_globally(self):
        self._queue(self.channel, RATE_LIMIT_PER_MINUTE)
        self._queue(self.other, 3)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE + 3)
        self.assertFalse(
            self.Outbox.search_count([("channel_id", "=", self.other.id),
                                      ("state", "=", "pending")])
        )

    def test_earlier_sends_inside_the_window_count_towards_the_cap(self):
        self._queue(self.channel, 2)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}):
            self.Outbox._flush(limit=100)
        self._queue(self.channel, RATE_LIMIT_PER_MINUTE)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE - 2)

    def test_sends_older_than_the_window_do_not_count(self):
        self._queue(self.channel, 2)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}):
            self.Outbox._flush(limit=100)
        self.Outbox.search([("state", "=", "sent")]).sent_at = (
            fields.Datetime.now() - timedelta(seconds=120)
        )
        self._queue(self.channel, RATE_LIMIT_PER_MINUTE)
        with patch.object(telegram_api, "call", return_value={"message_id": 1}) as call:
            self.Outbox._flush(limit=100)
        self.assertEqual(call.call_count, RATE_LIMIT_PER_MINUTE)
```

- [ ] **Bước 2: Chạy test, xác nhận FAIL / Run test to verify it fails**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: FAIL with `ImportError: cannot import name 'RATE_LIMIT_PER_MINUTE'`

- [ ] **Bước 3: Viết code tối thiểu / Write minimal implementation**

Trong `addons/erp_telegram_notify/models/telegram_outbox.py`, thêm hằng số ngay dưới `COALESCE_WINDOW`:

```python
# Telegram caps a bot at 20 messages per minute into one group. Stay under it
# so a burst degrades into a delay instead of a 429 and a temporary ban.
RATE_LIMIT_PER_MINUTE = 18
RATE_LIMIT_WINDOW = 60
```

Thêm field vào class `TelegramOutbox`, ngay dưới `telegram_message_id`:

```python
    sent_at = fields.Datetime(readonly=True, index=True)
```

Thay thế toàn bộ method `_flush` bằng:

```python
    @api.model
    def _flush(self, limit=50):
        """Send every due pending message, respecting the per-channel cap.

        Messages beyond a channel's minute budget stay ``pending`` and are
        picked up by the next cron pass.
        """
        now = fields.Datetime.now()
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        messages = self.search(
            [
                ("state", "=", "pending"),
                "|", ("next_retry_at", "=", False), ("next_retry_at", "<=", now),
                ("channel_id.bot_id.enabled", "=", True),
                ("channel_id.state", "=", "confirmed"),
            ],
            limit=limit,
        )
        budget = {}
        for message in messages:
            channel = message.channel_id
            if channel.id not in budget:
                already_sent = self.search_count([
                    ("channel_id", "=", channel.id),
                    ("sent_at", ">=", window_start),
                ])
                budget[channel.id] = RATE_LIMIT_PER_MINUTE - already_sent
            if budget[channel.id] <= 0:
                continue
            token = channel.bot_id.sudo().token
            if not token:
                continue
            try:
                result = telegram_api.call(token, "sendMessage", message._payload())
            except telegram_api.TelegramError as exc:
                message._schedule_retry(exc)
                continue
            budget[channel.id] -= 1
            message.write({
                "state": "sent",
                "last_error": False,
                "sent_at": fields.Datetime.now(),
                "telegram_message_id": (result or {}).get("message_id", 0),
            })
```

Thêm `sent_at` vào list view outbox trong `addons/erp_telegram_notify/views/telegram_outbox_views.xml`, ngay sau `<field name="state"/>`:

```xml
                <field name="sent_at"/>
```

Sửa `addons/erp_telegram_notify/tests/__init__.py`, thêm dòng cuối:

```python
from . import test_rate_limit
```

- [ ] **Bước 4: Chạy test, xác nhận PASS / Run test to verify it passes**

Run: `odoo -d testdb -u erp_telegram_notify --test-enable --test-tags /erp_telegram_notify --stop-after-init --log-level=test`
Expected: PASS — 5 tests trong `TestOutboxRateLimit`, và toàn bộ test Task 4 và 6 vẫn xanh / 5 tests in `TestOutboxRateLimit`, with all Task 4 and 6 tests still green

- [ ] **Bước 5: Commit**

```bash
git add addons/erp_telegram_notify
git commit -m "feat(telegram): cap outbound rate per channel to stay under Telegram limits"
```

---

## Kiểm tra thủ công sau khi xong / Manual verification after completion

Các bước này không tự động hoá được vì cần một bot Telegram thật.
EN: These steps cannot be automated — they need a real Telegram bot.

1. Tạo bot qua `@BotFather`, lấy token, tạo bản ghi `telegram.bot` và bấm **Set Webhook**.
   EN: Create a bot via `@BotFather`, take its token, create the `telegram.bot` record and press **Set Webhook**.
2. Thêm bot vào một group thử, gõ `/register`. Kỳ vọng: bot trả lời, và một `telegram.channel` trạng thái `pending` xuất hiện trong Odoo.
   EN: Add the bot to a test group and type `/register`. Expect a reply and a `pending` channel in Odoo.
3. Bấm **Confirm**, rồi bấm **Send Test Message**. Kỳ vọng: tin nhắn hiện trong group.
   EN: Press **Confirm**, then **Send Test Message**. Expect the message in the group.
4. Tạo một `base.automation` trên `res.partner`, trigger **On Save**, action type **Send Telegram**, trỏ vào kênh vừa xác nhận. Sửa tên một partner và lưu. Kỳ vọng: tin nhắn tới group trong vòng ~1–2 giây, có nút **Open in Odoo** mở đúng record.
   EN: Create a `base.automation` on `res.partner`, On Save trigger, Send Telegram action pointing at the confirmed channel. Rename a partner and save. Expect a message within ~1–2 seconds carrying a working **Open in Odoo** button.
5. Tắt `enabled` trên bot, sửa partner lần nữa. Kỳ vọng: dòng outbox đứng ở `pending`, không có tin nào được gửi.
   EN: Turn `enabled` off, edit the partner again. Expect a `pending` outbox row and no message sent.

## Rủi ro đã biết / Known risks

- **Telegram đang bị chặn tại Việt Nam** theo yêu cầu của Cục Viễn thông từ 5/2025, thực thi không đồng đều giữa các nhà mạng. Server Odoo có thể vẫn gọi được `api.telegram.org` trong khi điện thoại nhân viên sau ISP trong nước thì không nhận được. Công tắc `enabled` và `timeout=10` trong plan này chính là để chịu được tình huống đó mà không làm treo worker hay phình outbox.
  EN: Telegram is under an ISP-level block order in Vietnam since May 2025, enforced inconsistently. The Odoo server may still reach `api.telegram.org` while employees' phones behind local ISPs receive nothing. The `enabled` kill switch and the 10-second timeout exist precisely to absorb that without hanging workers or flooding the outbox.
- Kênh Telegram nằm ngoài ACL của Odoo. Mặc định `telegram_content_level = link_only` là có chủ ý — chuyển sang `full` là một quyết định về lộ dữ liệu, không phải một tuỳ chọn hiển thị.
  EN: A Telegram group sits outside Odoo's ACLs. The `link_only` default is deliberate — switching to `full` is a data-exposure decision, not a formatting preference.
