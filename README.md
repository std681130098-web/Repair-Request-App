# 🛠️ ระบบแจ้งซ่อมออนไลน์ (Online Repair Request System)

ระบบแจ้งซ่อมออนไลน์ พัฒนาด้วย **Django Framework** รองรับผู้ใช้งาน **3 บทบาท**
ครอบคลุมตั้งแต่การแจ้งซ่อม การมอบหมายงานให้ช่าง การซ่อม ไปจนถึงการตรวจรับและประเมินผล

> โครงงานรายวิชา **31901-2008 การพัฒนาซอฟต์แวร์รูปแบบเดฟออฟส์ (DevOps)**

---

## ✨ คุณสมบัติหลัก (Features)

### 👤 ผู้แจ้งซ่อม (Reporter)
- สมัครสมาชิก / เข้าสู่ระบบ
- แจ้งซ่อมใหม่ (หัวข้อ, ประเภท, รายละเอียด, สถานที่)
- ติดตามสถานะงานแบบ Timeline
- แก้ไข/ยกเลิกใบแจ้งซ่อมที่ยังไม่ดำเนินการ
- ประเมินความพึงพอใจ (ให้ดาว) เมื่องานเสร็จ

### 🧑‍💼 ผู้ดูแลระบบ (Admin)
- แดชบอร์ดภาพรวม + รายการที่ต้องดำเนินการ
- ตรวจสอบ/อนุมัติคำร้อง หรือ **ตีกลับ** พร้อมเหตุผล
- มอบหมายงานให้ช่างที่เหมาะสม
- ตรวจรับงาน (ผ่าน / ส่งกลับให้แก้ไข)
- รายงานสรุป (ตามสถานะ, ประเภทงาน, ภาระงานช่าง, คะแนนเฉลี่ย)

### 🔧 ช่างซ่อม (Technician)
- ดูงานที่ได้รับมอบหมาย
- รับงาน / เริ่มดำเนินการ
- บันทึกผลการซ่อม แล้วแจ้งงานเสร็จเพื่อส่งตรวจรับ

---

## 🧱 เทคโนโลยีที่ใช้ (Tech Stack)

| ส่วน | เทคโนโลยี |
|------|-----------|
| Backend | Python 3.12+ · Django 6.0 |
| Frontend | Django Templates · Bootstrap 5 · Bootstrap Icons |
| Database | SQLite (ค่าเริ่มต้น) |
| Font | Sarabun (ภาษาไทย) |
| DevOps | Git · GitHub · GitHub Actions (CI) |

---

## 🗂️ โครงสร้างฐานข้อมูล (5 ตาราง)

```
User ──1:M──> RepairRequest <──M:1── Category
User(ช่าง) ──1:M──> Assignment ──M:1──> RepairRequest
RepairRequest ──1:1──> Rating
```

| ตาราง | หน้าที่ |
|-------|---------|
| **User** | ผู้ใช้ระบบ + บทบาท (reporter / admin / technician) |
| **Category** | ประเภทงานซ่อม |
| **RepairRequest** | ใบแจ้งซ่อม + สถานะ |
| **Assignment** | การมอบหมายช่าง + บันทึกการซ่อม |
| **Rating** | การประเมินความพึงพอใจ |

---

## 🔄 ขั้นตอนการทำงาน (Workflow)

```
รอตรวจสอบ ──มอบหมาย──> มอบหมายแล้ว ──ช่างรับงาน──> กำลังดำเนินการ
     │                                                     │
   ตีกลับ                                              แจ้งเสร็จ
     │                                                     ▼
  (ผู้แจ้งแก้ไข) <───┐                                   รอตรวจรับ
                     │                                  │       │
                     └──────ส่งกลับให้แก้ไข─────────────┘   ตรวจรับผ่าน
                                                                 ▼
                                                          เสร็จสมบูรณ์ ──> ประเมินผล
```

---

## 🚀 วิธีติดตั้งและรัน (Getting Started)

```bash
# 1. clone โปรเจกต์
git clone <your-repo-url>
cd repair-system

# 2. สร้าง virtual environment (แนะนำ)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. ติดตั้ง dependencies
pip install -r requirements.txt

# 4. สร้างฐานข้อมูล
python manage.py migrate

# 5. ใส่ข้อมูลตัวอย่าง (พร้อมบัญชีทดสอบ)
python manage.py seed_data

# 6. รันเซิร์ฟเวอร์
python manage.py runserver
```

เปิดเบราว์เซอร์ที่ 👉 **http://127.0.0.1:8000/**

### 🔑 บัญชีทดสอบ (รหัสผ่าน `1234` ทุกบัญชี)

| บทบาท | Username |
|-------|----------|
| ผู้ดูแลระบบ | `admin` |
| ช่างซ่อม | `tech1`, `tech2` |
| ผู้แจ้งซ่อม | `user1`, `user2` |

---

## 🧪 การทดสอบ (Testing)

```bash
python manage.py test
```

มีชุดทดสอบอัตโนมัติ **18 เคส** ครอบคลุม models, สิทธิ์การเข้าถึง (access control),
และ workflow ทั้งกระบวนการ — รันอัตโนมัติทุกครั้งที่ push ผ่าน GitHub Actions

---

## 📁 โครงสร้างโปรเจกต์

```
repair-system/
├── config/              # การตั้งค่าโปรเจกต์ Django
├── repairs/             # แอปหลัก
│   ├── models.py        # 5 ตาราง
│   ├── views.py         # ตรรกะ workflow
│   ├── forms.py         # ฟอร์ม
│   ├── decorators.py    # ควบคุมสิทธิ์ตามบทบาท
│   ├── tests.py         # ชุดทดสอบอัตโนมัติ
│   └── management/commands/seed_data.py
├── templates/           # หน้าเว็บ (Bootstrap 5)
├── static/css/          # สไตล์
├── .github/workflows/   # CI (GitHub Actions)
├── requirements.txt
├── CHANGELOG.md
└── README.md
```

---

## 🤝 การพัฒนาแบบทีม (DevOps / Git Workflow)

> 📖 **ทีมอ่านคู่มือฉบับเต็มได้ที่ [`docs/TEAM-GIT-WORKFLOW.md`](docs/TEAM-GIT-WORKFLOW.md)**
> — วิธี clone, แตก branch, เปิด PR, review, merge พร้อมคำสั่ง copy-paste และ ✅ checklist ก่อนส่งงาน

1. แต่ละคนแยก branch ของตัวเอง เช่น `feature/login`, `feature/report`
2. commit ด้วยข้อความที่ชัดเจน (เช่น `feat: เพิ่มหน้าประเมินผล`)
3. เปิด Pull Request → ให้เพื่อนในทีม review → merge เข้า `main`
4. ทุก PR จะถูกทดสอบอัตโนมัติด้วย GitHub Actions ก่อน merge
5. บันทึกการเปลี่ยนแปลงแต่ละเวอร์ชันใน [`CHANGELOG.md`](CHANGELOG.md)

### 👥 ตารางแบ่งหน้าที่

> ⚠️ **ทีมต้องกรอกชื่อจริงในตารางนี้ก่อนส่งงาน** (ลบบรรทัดเตือนนี้เมื่อกรอกเสร็จ)

| ชื่อ-นามสกุล | รหัสนักศึกษา | หน้าที่รับผิดชอบ | branch |
|-------------|-------------|------------------|--------|
| _(กรอกชื่อ)_ | | ออกแบบฐานข้อมูล / Models | `feature/models` |
| _(กรอกชื่อ)_ | | ระบบสมาชิก & สิทธิ์ (Auth) | `feature/auth` |
| _(กรอกชื่อ)_ | | หน้าแจ้งซ่อม & workflow | `feature/workflow` |
| _(กรอกชื่อ)_ | | หน้า UI/UX & Dashboard | `feature/ui` |
| _(กรอกชื่อ)_ | | รายงาน & การทดสอบ / DevOps | `feature/report-tests` |

---

## 📄 License

จัดทำเพื่อการศึกษา — รายวิชา 31901-2008 การพัฒนาซอฟต์แวร์รูปแบบเดฟออฟส์ (DevOps)
