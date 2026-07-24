# 👥 คู่มือการทำงานเป็นทีมด้วย Git/GitHub (DevOps)

> คู่มือนี้ทำขึ้นเพื่อให้ทีมสร้าง **ประวัติการทำงานร่วมกันจริง** บน GitHub
> ซึ่งเป็นเกณฑ์ให้คะแนนข้อ 2 (Git/GitHub มีคำอธิบายเวอร์ชัน) และข้อ 3 (การทำงานเป็นทีม/DevOps) รวม ~20 คะแนน

---

## ⚠️ อ่านก่อน — ทำไมต้องทำตามนี้

ตอนตรวจ อาจารย์จะเปิดหน้า **GitHub → Insights → Contributors** และดู **ประวัติ commit**
สิ่งที่ต้อง "เห็น" คือ:

| อาจารย์อยากเห็น | ถ้าไม่ทำจะเห็น (เสียคะแนน) |
|-----------------|---------------------------|
| สมาชิกทุกคนมี commit จากบัญชี GitHub ตัวเอง | commit คนเดียวทั้งหมด |
| commit กระจายหลายวัน | commit รวดเดียวไม่กี่วินาที |
| มี branch `feature/*` และ **Pull Request** | มีแต่ branch เดียว ไม่มี PR |
| PR ถูก **review** โดยเพื่อนก่อน merge | ไม่มีร่องรอยการรีวิว |

> ❗ **สำคัญ:** การใส่ `Co-authored-by` ในข้อความ commit **ไม่ทำให้** กราฟ Contributors ขึ้นชื่อเพื่อน
> เพื่อนแต่ละคน **ต้อง commit + push จากบัญชี GitHub ของตัวเองจริง ๆ**

---

## 1️⃣ ตั้งค่าครั้งแรก (ทำครั้งเดียว โดยหัวหน้าทีม 1 คน)

```bash
# หัวหน้าทีมสร้าง repo บน GitHub (ตั้งเป็น Public หรือเชิญอาจารย์เป็น collaborator)
# แล้ว push โค้ดที่มีอยู่ขึ้นไป
cd repair-system
git remote add origin https://github.com/<username>/repair-system.git
git branch -M main
git push -u origin main
```

จากนั้นบน GitHub:
1. ไปที่ **Settings → Collaborators → Add people** เชิญเพื่อนทุกคนเข้าร่วม
2. (แนะนำ) **Settings → Branches → Add branch protection rule** สำหรับ `main`
   - ✅ *Require a pull request before merging*
   - ✅ *Require approvals* (อย่างน้อย 1)
   > ทำให้ทุกคน **ต้อง** เปิด PR และมีคนรีวิว = ตรงเกณฑ์พอดี

---

## 2️⃣ ตั้งค่าเครื่องตัวเอง (สมาชิกทุกคนทำ)

```bash
# ตั้งชื่อ/อีเมลให้ตรงกับบัญชี GitHub ของตัวเอง (สำคัญมาก! ชื่อบน commit มาจากตรงนี้)
git config --global user.name "ชื่อจริงของคุณ"
git config --global user.email "อีเมลที่ผูกกับ GitHub ของคุณ"

# clone โปรเจกต์ลงเครื่อง
git clone https://github.com/<username>/repair-system.git
cd repair-system

# ติดตั้งและรันตาม README
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

---

## 3️⃣ วงจรการทำงานต่อ 1 งาน (ทำซ้ำทุกครั้งที่จะเพิ่ม/แก้ฟีเจอร์)

```bash
# 1. อัปเดต main ให้ล่าสุดก่อนเสมอ
git checkout main
git pull origin main

# 2. แตก branch ใหม่ตามงานที่รับผิดชอบ
git checkout -b feature/report-page      # ตัวอย่างชื่อ branch

# 3. ทำงาน... แล้ว commit เป็นช่วง ๆ (อย่ารวบเป็น commit เดียว)
git add <ไฟล์ที่แก้>
git commit -m "feat: เพิ่มกราฟสรุปงานตามสถานะในหน้ารายงาน"
#   ...แก้เพิ่ม...
git commit -m "style: ปรับสีการ์ดสถิติให้อ่านง่ายขึ้น"

# 4. push branch ขึ้น GitHub
git push -u origin feature/report-page
```

จากนั้นบน GitHub:
5. กด **Compare & pull request** → เขียนอธิบายว่าทำอะไร (มี template ให้แล้ว)
6. ใส่เพื่อนเป็น **Reviewer**
7. เพื่อนกด **Review → Approve** (หรือคอมเมนต์ให้แก้)
8. เมื่อ CI (สีเขียว ✅) ผ่านและมีคน approve → กด **Merge pull request**
9. ลบ branch ได้ (GitHub มีปุ่มให้)

> 🔁 ทำแบบนี้ทุกคน ทุกงาน ประวัติจะสวยและตรงเกณฑ์เอง

---

## 4️⃣ รูปแบบข้อความ commit (Conventional Commits)

ใช้คำนำหน้าให้ประวัติอ่านง่าย:

| คำนำหน้า | ใช้เมื่อ | ตัวอย่าง |
|----------|---------|----------|
| `feat:` | เพิ่มฟีเจอร์ใหม่ | `feat: เพิ่มหน้าประเมินความพึงพอใจ` |
| `fix:` | แก้บั๊ก | `fix: แก้ปุ่มตีกลับกดแล้ว error` |
| `style:` | ปรับ UI/รูปแบบ | `style: จัดหน้า dashboard ให้ responsive` |
| `docs:` | แก้เอกสาร | `docs: อัปเดตวิธีติดตั้งใน README` |
| `test:` | เพิ่ม/แก้เทสต์ | `test: เพิ่มเทสต์ workflow การมอบหมายงาน` |
| `refactor:` | ปรับโครงสร้างโค้ด | `refactor: แยกฟังก์ชันตรวจสิทธิ์` |

---

## 5️⃣ แบ่งงานให้แต่ละคนมี branch/PR ของตัวเอง

ให้แต่ละคน "เป็นเจ้าของ" ส่วนใดส่วนหนึ่ง เพื่อให้มี PR แยกกันชัดเจน
(อ้างอิงตารางแบ่งหน้าที่ใน [README](../README.md#-การพัฒนาแบบทีม-devops--git-workflow)):

| สมาชิก | branch แนะนำ | ขอบเขต |
|--------|--------------|--------|
| ผู้ออกแบบฐานข้อมูล | `feature/models` | models.py, migrations, admin.py |
| ผู้ทำระบบสมาชิก | `feature/auth` | forms.py, decorators.py, signup |
| ผู้ทำ workflow | `feature/workflow` | views.py, urls.py |
| ผู้ทำ UI/UX | `feature/ui` | templates/, static/ |
| ผู้ทำรายงาน & ทดสอบ | `feature/report-tests` | report, tests.py, CI |

> แม้โค้ดหลักจะเสร็จแล้ว แต่ละคนยังสามารถแตก branch มาปรับปรุงส่วนของตัวเอง
> (เพิ่มคอมเมนต์, ปรับข้อความ, เพิ่มเทสต์, แต่งหน้าตา) แล้วเปิด PR จริงได้ — นับเป็นผลงานร่วมทั้งสิ้น

---

## ✅ Checklist ก่อนส่งงาน

- [ ] repo อยู่บน GitHub และเชิญอาจารย์/เพื่อนเป็น collaborator แล้ว
- [ ] สมาชิก **ทุกคน** มี commit จากบัญชีตัวเอง (เช็คที่ Insights → Contributors)
- [ ] มี **Pull Request** อย่างน้อยคนละ 1 อัน และถูก merge เข้า `main` แล้ว
- [ ] แต่ละ PR มีการ **review/approve** โดยเพื่อน
- [ ] CI (GitHub Actions) ขึ้นสีเขียว ✅ บน PR และบน `main`
- [ ] กรอกชื่อจริงในตารางแบ่งหน้าที่ใน `README.md` แล้ว
- [ ] อัปเดต `CHANGELOG.md` ตามเวอร์ชันที่เพิ่ม

---

_ทำเพื่อรายวิชา 31901-2008 การพัฒนาซอฟต์แวร์รูปแบบเดฟออฟส์ (DevOps)_
