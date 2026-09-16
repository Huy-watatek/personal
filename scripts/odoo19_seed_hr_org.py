# =============================================================================
# SEED HR ORG — Odoo 19 CE
# Tạo hàng loạt Phòng ban (hr.department) + Vị trí tuyển dụng (hr.job)
# theo cơ cấu chuẩn của một công ty công nghệ.
#
# CÁCH DÙNG
#   Settings > Technical > Automation > Server Actions (Model: bất kỳ)
#   > tab "Code" → dán toàn bộ đoạn này.
#   Hoặc dán vào ô "Code" của một Scheduled Action (ir.cron).
#
#   B1. Để cờ chạy thử = True  → bấm Run. Hiện bảng kê, KHÔNG ghi gì vào DB.
#   B2. Đổi thành False        → bấm Run lần nữa. Ghi thật.
#   B3. Xoá / tắt action sau khi chạy xong.
#
#   Nếu chạy bằng ir.cron thì phải để False, vì chế độ chạy thử rollback
#   bằng cách raise UserError → cron sẽ báo lỗi.
#
# AN TOÀN
#   - Idempotent: chạy lại nhiều lần không tạo trùng (khớp theo tên + công ty
#     + phòng ban cha). Chỉ tạo mới, không sửa, không xoá bản ghi đang có.
#   - Tìm cả bản ghi đã archive (active_test=False) nên không hồi sinh rác.
#   - Tuân thủ safe_eval của server action: không import, không gán thuộc tính.
#
# GHI CHÚ VỀ "JOB TITLE"
#   Odoo không có model Job Title riêng. `job_title` là trường Char trên
#   hr.version (kế thừa sang hr.employee), tự động lấy theo tên Job Position
#   khi gán nhân viên vào vị trí. Tạo xong hr.job là có sẵn danh mục chức danh.
#
# TÁC DỤNG PHỤ
#   hr_recruitment tạo một mail.alias cho mỗi hr.job (alias mixin). Chạy script
#   này sẽ sinh ra đúng bấy nhiêu alias email — bình thường, không cần xử lý.
# =============================================================================

DRY_RUN = True                      # True = chạy thử: xem trước rồi rollback
COMPANY = env.company               # đổi nếu chạy cho công ty khác
RECRUITMENT_TARGET = 0              # trường 'Target' mặc định mỗi vị trí
CONTRACT_TYPE_XMLID = "hr.contract_type_full_time"   # "" để bỏ qua
MAX_REPORT_LINES = 40               # số dòng chi tiết hiện trong dialog

# (Tên phòng ban, Tên phòng ban cha, [Danh sách vị trí tuyển dụng])
# Phòng ban cha PHẢI đứng trước phòng ban con trong danh sách này.
ORG = [
    ("Ban Giám đốc", None, [
        "Tổng Giám đốc (CEO)",
        "Giám đốc Công nghệ (CTO)",
        "Giám đốc Sản phẩm (CPO)",
        "Giám đốc Vận hành (COO)",
        "Giám đốc Tài chính (CFO)",
    ]),

    ("Khối Công nghệ", None, []),
    ("Phát triển Phần mềm", "Khối Công nghệ", [
        "Backend Developer",
        "Frontend Developer",
        "Fullstack Developer",
        "Mobile Developer (iOS/Android)",
        "Technical Lead",
        "Software Architect",
        "Engineering Manager",
        "Thực tập sinh Lập trình",
    ]),
    ("Kiểm thử Chất lượng", "Khối Công nghệ", [
        "QA Engineer",
        "QA Automation Engineer",
        "QA Lead",
    ]),
    ("Hạ tầng & DevOps", "Khối Công nghệ", [
        "DevOps Engineer",
        "Site Reliability Engineer",
        "Cloud Engineer",
        "System Administrator",
    ]),
    ("Dữ liệu & AI", "Khối Công nghệ", [
        "Data Engineer",
        "Data Analyst",
        "Data Scientist",
        "Machine Learning Engineer",
        "BI Developer",
    ]),
    ("An toàn Thông tin", "Khối Công nghệ", [
        "Security Engineer",
        "Chuyên viên An toàn Thông tin",
    ]),

    ("Khối Sản phẩm", None, []),
    ("Quản lý Sản phẩm", "Khối Sản phẩm", [
        "Product Manager",
        "Product Owner",
        "Business Analyst",
    ]),
    ("Thiết kế", "Khối Sản phẩm", [
        "UI/UX Designer",
        "Product Designer",
        "Graphic Designer",
    ]),

    ("Khối Kinh doanh", None, []),
    ("Kinh doanh", "Khối Kinh doanh", [
        "Nhân viên Kinh doanh",
        "Trưởng nhóm Kinh doanh",
        "Giám đốc Kinh doanh",
        "Account Manager",
        "Presales Consultant",
    ]),
    ("Marketing", "Khối Kinh doanh", [
        "Digital Marketing Executive",
        "Content Marketing Executive",
        "Performance Marketing Executive",
        "SEO Specialist",
        "Trưởng phòng Marketing",
    ]),

    ("Khối Vận hành", None, []),
    ("Quản lý Dự án", "Khối Vận hành", [
        "Project Manager",
        "Scrum Master",
        "Chuyên viên PMO",
    ]),
    ("Chăm sóc Khách hàng", "Khối Vận hành", [
        "Nhân viên Chăm sóc Khách hàng",
        "Technical Support Engineer",
        "Customer Success Manager",
    ]),

    ("Khối Hành chính & Nhân sự", None, []),
    ("Nhân sự", "Khối Hành chính & Nhân sự", [
        "Chuyên viên Tuyển dụng",
        "Chuyên viên C&B",
        "Chuyên viên Đào tạo",
        "HR Business Partner",
        "Trưởng phòng Nhân sự",
    ]),
    ("Kế toán & Tài chính", "Khối Hành chính & Nhân sự", [
        "Kế toán viên",
        "Kế toán Tổng hợp",
        "Kế toán trưởng",
        "Chuyên viên Phân tích Tài chính",
    ]),
    ("Hành chính - Pháp chế", "Khối Hành chính & Nhân sự", [
        "Nhân viên Hành chính",
        "Lễ tân",
        "Chuyên viên Pháp chế",
        "IT Helpdesk",
    ]),
]

# ---------------------------------------------------------------------------
# Thực thi
# ---------------------------------------------------------------------------
Dept = env["hr.department"].with_context(active_test=False)
Job = env["hr.job"].with_context(active_test=False)

contract_type = None
if CONTRACT_TYPE_XMLID:
    contract_type = env.ref(CONTRACT_TYPE_XMLID, raise_if_not_found=False)

dept_map = {}
report = []
n_dept_new = 0
n_job_new = 0

# 1) Phòng ban — danh sách đã xếp cha trước con
for dept_name, parent_name, _jobs in ORG:
    parent = dept_map.get(parent_name)
    if parent_name and not parent:
        parent = Dept.search(
            [("name", "=", parent_name), ("company_id", "=", COMPANY.id)], limit=1
        )
    parent_id = parent.id if parent else False

    dept = Dept.search([
        ("name", "=", dept_name),
        ("company_id", "=", COMPANY.id),
        ("parent_id", "=", parent_id),
    ], limit=1)

    if not dept:
        dept = Dept.create({
            "name": dept_name,
            "parent_id": parent_id,
            "company_id": COMPANY.id,
        })
        n_dept_new += 1
        report.append(f"[+] Phòng ban : {dept_name}")

    dept_map[dept_name] = dept

# 2) Vị trí tuyển dụng
seq = 0
for dept_name, _parent_name, jobs in ORG:
    dept = dept_map[dept_name]
    for job_name in jobs:
        seq += 10
        exists = Job.search([
            ("name", "=", job_name),
            ("company_id", "=", COMPANY.id),
            ("department_id", "=", dept.id),
        ], limit=1)
        if exists:
            continue

        vals = {
            "name": job_name,
            "department_id": dept.id,
            "company_id": COMPANY.id,
            "no_of_recruitment": RECRUITMENT_TARGET,
            "sequence": seq,
        }
        if contract_type:
            vals["contract_type_id"] = contract_type.id

        Job.create(vals)
        n_job_new += 1
        report.append(f"    [+] Vị trí : {job_name}  ← {dept_name}")

# 3) Báo cáo
total_depts = len(ORG)
total_jobs = sum(len(j) for _n, _p, j in ORG)
summary = "\n".join([
    f"Công ty           : {COMPANY.name}",
    f"Phòng ban tạo mới : {n_dept_new} / {total_depts}",
    f"Vị trí tạo mới    : {n_job_new} / {total_jobs}",
])

if report:
    shown = report[:MAX_REPORT_LINES]
    detail = "\n".join(shown)
    if len(report) > MAX_REPORT_LINES:
        detail += f"\n... và {len(report) - MAX_REPORT_LINES} dòng nữa"
else:
    detail = "(không có gì để tạo — dữ liệu đã đầy đủ)"

if DRY_RUN:
    raise UserError(
        "CHẠY THỬ — đã rollback, chưa ghi gì vào DB.\n"
        "Đổi DRY_RUN = False rồi chạy lại để ghi thật.\n\n"
        + summary + "\n\n" + detail
    )

log(summary + "\n\n" + detail)
_logger.info("seed_hr_org: %s", summary.replace("\n", " | "))
