# ERP Telegram Notify (Odoo 19)

Đẩy thông báo từ Odoo vào Telegram khi dữ liệu thay đổi. Toàn bộ cấu hình nằm
trong **Automation Rules** có sẵn của Odoo — chọn model bất kỳ, trigger bất kỳ,
điều kiện bất kỳ, rồi chọn ai nhận.

## Cài đặt

```bash
# 1. copy addon vào addons_path của bạn
cp -r addons/erp_telegram_notify /path/to/your/odoo/addons/

# 2. cập nhật danh sách app rồi cài
odoo -d <db> -u base --stop-after-init
odoo -d <db> -i erp_telegram_notify --stop-after-init

# 3. chạy test (khuyến nghị trước khi dùng thật)
odoo -d <db> -u erp_telegram_notify --test-enable \
     --test-tags /erp_telegram_notify --stop-after-init --log-level=test
```

Yêu cầu: Odoo 19.0, và Odoo phải ra được Internet tới `api.telegram.org`.
Chiều inbound (webhook) cần Odoo có URL HTTPS công khai.

## Thiết lập lần đầu

1. **Tạo bot**: chat với `@BotFather` → `/newbot` → lấy token.
2. **Settings → Telegram → Bots**: tạo bản ghi, dán token, điền *Bot Username*
   (bắt buộc nếu muốn liên kết tài khoản cá nhân), bấm **Set Webhook**.
3. **Đăng ký group**: thêm bot vào group Telegram, gõ `/register` trong group đó.
   Channel xuất hiện ở **Telegram → Channels** với trạng thái *Pending*.
   Mở ra bấm **Confirm**, rồi **Send Test Message** để kiểm chứng.
4. **Liên kết cá nhân** (nếu cần gửi DM): mỗi user vào profile → tab **Telegram**
   → **Generate Linking Link** → quét QR bằng điện thoại. Bind xong tự động.

## Cấu hình một thông báo

**Settings → Technical → Automation Rules → New**

| Ô | Điền gì |
|---|---|
| Model | Model bất kỳ, kể cả model custom |
| Trigger | On Save / On Creation / khi một field đổi / theo lịch |
| Before Update Domain, Apply on | Điều kiện lọc |
| Actions → Type | **Send Telegram** |

Trong action **Send Telegram**:

- **Responsible** — vai trò tìm ra người chịu trách nhiệm. Họ nhận DM **kèm nút
  hành động**.
- **Also Notify** — người theo dõi. Nhận cùng thông tin nhưng **không có nút**,
  nên không ai bấm duyệt nhầm.
- **Telegram Groups** — group luôn nhận.
- **Fallback Group** — nơi tin rơi về khi không tìm được ai. Không khai ô này thì
  một task chưa gán ai sẽ mất thông báo trong im lặng.
- **Skip the Author** — bỏ qua chính người vừa gây ra thay đổi (mặc định bật).
- **Preview** — chọn một record thật, xem trước ai sẽ nhận và tin trông thế nào,
  trước khi bật rule.

## Recipient Roles

**Settings → Telegram → Recipient Roles**. Một role định nghĩa "tìm người từ
record" một lần rồi dùng lại ở mọi rule. Bốn cách tìm:

| Kiểu | Ví dụ |
|---|---|
| Field on the record | `user_id`, `partner_id.user_id`, `employee_id.parent_id` |
| Followers | Người đang theo dõi record |
| Members of a group | Toàn bộ user trong nhóm "Kế toán trưởng" |
| Specific users | Danh sách cố định |

Đường dẫn field có thể kết thúc ở `res.users`, `res.partner`, hoặc bất kỳ model
nào có `user_id` — nên `employee_id.parent_id` (sếp trực tiếp) hoạt động luôn.

Đổi cơ cấu tổ chức thì sửa role một chỗ, mọi rule ăn theo.

## Nút hành động trong Telegram

**Settings → Telegram → Action Buttons**: khai model + tên method public
(`action_approve`, `action_confirm`, ...). Gắn button vào rule là xong.

Hai lớp bảo vệ:

- Callback chỉ mang **id của button**, không bao giờ mang tên method. Không thể
  gọi method tuỳ ý bằng cách chế callback.
- Method chạy dưới `with_user()` của người Telegram đã liên kết, nên **ACL và
  record rule của Odoo vẫn quyết định**. Người chưa liên kết không làm gì được.

## Vận hành

- **Telegram → Outbox**: mọi tin đi qua đây. Lọc theo *Failed* để soi lỗi, có nút
  **Retry**.
- **Sending Enabled** trên bot là công tắc tắt toàn cục — dùng khi Telegram không
  truy cập được, tránh outbox phình.
- Backoff khi lỗi: 1 phút → 5 phút → 30 phút → 2 giờ → 6 giờ, quá 5 lần thì
  `failed`. Gặp `429` thì tôn trọng đúng `retry_after` Telegram trả về.
- Trần 18 tin/phút mỗi chat (Telegram cho 20). Vượt thì tin nằm chờ cron phút sau.
- Tin trùng cho cùng một record trong 60 giây được gộp làm một.

## Ghi chú thiết kế

- **Không gọi HTTP trong transaction ghi dữ liệu.** Tin được ghi vào
  `telegram.outbox` trong transaction, đẩy đi ở `cr.postcommit` (độ trễ ~1 giây),
  `ir.cron` mỗi phút làm lưới an toàn. Transaction rollback thì tin cũng bị rollback
  theo, thay vì đã bay đi rồi.
- **Group Telegram nằm ngoài ACL của Odoo.** Mặc định *Content = Link only* là có
  chủ ý: tin chỉ mang tên record và nút mở, dữ liệu vẫn nằm sau đăng nhập Odoo.
  Chuyển sang *Full content* là một quyết định về lộ dữ liệu.
- Telegram HTML chỉ nhận một tập thẻ rất nhỏ. `tools/html2tg.py` chuyển HTML của
  Odoo sang tập đó và cắt ở 4096 ký tự mà không để hở thẻ.

## Trạng thái kiểm thử

Test suite nằm ở `tests/`. Logic thuần Python (`html2tg`) đã được chạy và pass.
Phần cần Odoo runtime **chưa được chạy trong môi trường build** — hãy chạy lệnh
test ở mục Cài đặt trên instance của bạn trước khi dùng thật.
