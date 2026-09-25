# HĐQT Executive Dashboard (Odoo 19 CE)

Một trang duy nhất cho ban lãnh đạo tại **`/hdqt/dashboard`**, gom số từ các
phân hệ chuẩn của Odoo. Không có bảng số liệu song song nào phải đồng bộ — mọi
con số đọc thẳng từ cột đã lưu của model gốc.

## Số lấy từ đâu

| Khối | Model | Cột |
|---|---|---|
| Doanh số chốt | `sale.order` | `amount_total`, `date_order`, `state`, `partner_id` |
| Doanh thu xuất HĐ, công nợ | `account.move` | `amount_total_signed`, `amount_residual_signed`, `invoice_date`, `invoice_date_due`, `move_type`, `state`, `payment_state` |
| Giá trị tồn kho | `stock.quant` | `value` (từ `stock_account`), `location_id.usage` |
| Phiếu kho | `stock.picking` | `state`, `scheduled_date` |
| Lệnh sản xuất | `mrp.production` | `state` |

## Cài đặt

```bash
cp -r addons/hdqt_dashboard /path/to/odoo/addons/
odoo -d <db> -u base --stop-after-init
odoo -d <db> -i hdqt_dashboard --stop-after-init

# test
odoo -d <db> -u hdqt_dashboard --test-enable \
     --test-tags /hdqt_dashboard --stop-after-init --log-level=test
```

Sau khi cài: **Settings → Users** → gán nhóm **Board Dashboard Viewer** cho ai
được xem, rồi mở `/hdqt/dashboard` (hoặc menu **HĐQT → Dashboard**).

## Chạy được trên bất kỳ tập phân hệ nào

Module chỉ `depends` vào `base` và `web`. Mỗi khối tự kiểm tra model của nó có
tồn tại không; chưa cài `mrp` thì thẻ Lệnh sản xuất tự ẩn, chưa cài `sale` thì
khối doanh số biến mất. Không ép cài thêm gì.

Riêng **Giá trị tồn kho** cần `stock_account` (tự động cài kèm khi có cả
`stock` và `account`). Thiếu nó thì thẻ này không hiện.

## Về quyền truy cập — đọc kỹ chỗ này

Dashboard đọc dữ liệu **với quyền nâng cao (`sudo`)**. Lý do: thành viên HĐQT
không phải kế toán, không nên bắt họ có quyền đọc `account.move` chỉ để nhìn
một con số tổng.

Hệ quả: **nhóm `Board Dashboard Viewer` là cổng duy nhất** quyết định ai thấy
số liệu toàn công ty. Cấp nhóm này một cách có cân nhắc.

Vì `sudo` cũng bỏ qua record rule đa công ty, **mọi domain đều pin `company_id`
tường minh** theo danh sách công ty mà người dùng thực sự được phép xem. Tham số
`company_ids` trên URL chỉ có thể **thu hẹp** phạm vi, không bao giờ mở rộng —
có test cho việc này (`test_companies_cannot_be_widened_by_the_query_string`).

## Bộ lọc

Một hàng trên cùng: kỳ dựng sẵn (Tháng này / Quý này / Năm nay / 30 ngày), khoảng
ngày tuỳ chọn, và chọn công ty khi người dùng có nhiều hơn một.

Mỗi KPI so với **kỳ liền trước có cùng độ dài**, hiển thị bằng mũi tên + dấu +
phần trăm, nên hướng tăng/giảm không phụ thuộc riêng vào màu.

Hai chỉ số là **ảnh chụp tại thời điểm hiện tại**, không theo kỳ lọc, vì hỏi
"công nợ quá hạn tháng trước" không có nghĩa: *Phải thu quá hạn* và *Giá trị tồn
kho*. Phần gợi ý dưới mỗi thẻ ghi rõ điều này.

## Về biểu đồ

Vẽ bằng SVG viết tay, không phụ thuộc thư viện ngoài:

- Bảng màu đã chạy qua validator: 2 slot categorical cho biểu đồ đường, một dải
  đơn sắc thứ bậc cho các nhóm tuổi nợ. Dark mode là bộ step chọn riêng cho nền
  tối, không phải đảo màu tự động.
- Bar tối đa 24px, bo 4px ở đầu dữ liệu và vuông ở chân trục; line 2px; điểm mốc
  ≥8px có viền 2px màu nền; gridline hairline liền nét.
- **Một trục duy nhất.** Doanh số và doanh thu cùng đơn vị tiền nên dùng chung
  trục; không bao giờ dựng biểu đồ hai trục y.
- Hover có crosshair + tooltip; mỗi biểu đồ kèm **Xem dạng bảng** để không phải
  đọc bằng màu.
- Nhãn dài được cắt bằng cách **đo glyph thật** (`getComputedTextLength`), không
  ước lượng theo số ký tự — ước lượng sai nặng với tiếng Việt có dấu.

## Trạng thái kiểm thử

- **Đã chạy thật:** render trang bằng Chromium với dữ liệu giả, chụp cả light và
  dark ở 1440px. Không có lỗi console, không tràn ngang, không nhãn đè nhau. Bước
  này bắt được 3 lỗi đã sửa: nhãn khách hàng bị lặp chữ, nhãn dính vào bar, và số
  VND làm vỡ thẻ KPI.
- **Chưa chạy:** test phía Odoo (`tests/`) — môi trường build không có Odoo
  instance. Chạy lệnh test ở mục Cài đặt trước khi dùng thật.
