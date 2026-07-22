"""
สร้างข้อมูลตัวอย่างสำหรับสาธิต/ทดสอบระบบ.

ใช้:  python manage.py seed_data
บัญชีทดสอบทั้งหมดใช้รหัสผ่าน  1234
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from repairs.models import Assignment, Category, Rating, RepairRequest, User

PW = "1234"


class Command(BaseCommand):
    help = "สร้างข้อมูลตัวอย่าง (ผู้ใช้ 3 บทบาท, ประเภทงาน, ใบแจ้งซ่อมตัวอย่าง)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fresh", action="store_true",
            help="ลบข้อมูลใบแจ้งซ่อม/มอบหมาย/ประเมิน เดิมก่อนสร้างใหม่",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts["fresh"]:
            Rating.objects.all().delete()
            Assignment.objects.all().delete()
            RepairRequest.objects.all().delete()
            self.stdout.write("ล้างข้อมูลใบแจ้งซ่อมเดิมแล้ว")

        # --- superuser / admin ---
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults=dict(
                first_name="แอดมิน ใจดี", role=User.Role.ADMIN,
                is_staff=True, is_superuser=True, phone="02-111-1111",
            ),
        )
        if created:
            admin.set_password(PW); admin.save()

        # --- technicians ---
        techs = []
        for uname, name in [("tech1", "สมชาย ช่างเก่ง"), ("tech2", "สมหญิง ช่างดี")]:
            t, c = User.objects.get_or_create(
                username=uname,
                defaults=dict(first_name=name, role=User.Role.TECHNICIAN, phone="08x-xxx-xxxx"),
            )
            if c:
                t.set_password(PW); t.save()
            techs.append(t)

        # --- reporters ---
        reporters = []
        for uname, name in [("user1", "นภา ผู้ใช้งาน"), ("user2", "ธนา พนักงาน")]:
            u, c = User.objects.get_or_create(
                username=uname,
                defaults=dict(first_name=name, role=User.Role.REPORTER, phone="08x-xxx-xxxx"),
            )
            if c:
                u.set_password(PW); u.save()
            reporters.append(u)

        # --- categories ---
        cat_names = ["ไฟฟ้า", "ประปา", "เครื่องปรับอากาศ", "คอมพิวเตอร์/เครือข่าย", "เฟอร์นิเจอร์/อาคาร"]
        cats = {n: Category.objects.get_or_create(name=n)[0] for n in cat_names}

        # --- sample requests across the whole workflow ---
        now = timezone.now()
        samples = [
            # (reporter, category, title, location, target_status)
            (reporters[0], "เครื่องปรับอากาศ", "แอร์ห้องประชุม 201 ไม่เย็น มีน้ำหยด", "อาคาร 2 ชั้น 2", "pending"),
            (reporters[1], "ไฟฟ้า", "หลอดไฟทางเดินชั้น 3 ดับหลายจุด", "อาคาร 1 ชั้น 3", "pending"),
            (reporters[0], "คอมพิวเตอร์/เครือข่าย", "เครื่องพิมพ์ห้องธุรการต่อเน็ตไม่ได้", "ห้องธุรการ", "assigned"),
            (reporters[1], "ประปา", "ก๊อกน้ำห้องน้ำชายชั้น 1 รั่ว", "อาคาร 1 ชั้น 1", "in_progress"),
            (reporters[0], "เฟอร์นิเจอร์/อาคาร", "เก้าอี้ห้องเรียน 305 ชำรุด 4 ตัว", "อาคาร 3 ชั้น 5", "review"),
            (reporters[1], "ไฟฟ้า", "ปลั๊กไฟห้องพักครูไม่มีไฟ", "ห้องพักครู", "done"),
            (reporters[0], "ประปา", "ชักโครกชั้น 2 กดไม่ลง", "อาคาร 2 ชั้น 2", "returned"),
        ]

        made = 0
        for i, (rep, cat, title, loc, target) in enumerate(samples):
            req = RepairRequest.objects.create(
                reporter=rep, category=cats[cat], title=title,
                detail="รายละเอียดปัญหาโดยผู้แจ้ง (ข้อมูลตัวอย่าง)",
                location=loc, status="pending",
                created_at=now - timezone.timedelta(days=len(samples) - i),
            )
            tech = techs[i % len(techs)]

            if target in ("assigned", "in_progress", "review", "done"):
                a = Assignment.objects.create(request=req, technician=tech)
                req.status = "assigned"
            if target in ("in_progress", "review", "done"):
                req.status = "in_progress"
            if target in ("review", "done"):
                a.work_detail = "ตรวจสอบและเปลี่ยนอะไหล่เรียบร้อย ทดสอบการใช้งานปกติ"
                a.work_date = now
                a.save()
                req.status = "review"
            if target == "done":
                req.status = "done"
            if target == "returned":
                req.status = "returned"
                req.admin_note = "กรุณาระบุหมายเลขห้องและชั้นให้ชัดเจน"

            req.save()

            if target == "done":
                Rating.objects.create(request=req, score=5, comment="ช่างมาซ่อมเร็ว บริการดีมากครับ")
            made += 1

        self.stdout.write(self.style.SUCCESS(
            f"เสร็จสิ้น: ผู้ใช้ {User.objects.count()} คน · "
            f"ประเภทงาน {Category.objects.count()} · ใบแจ้งซ่อม {made} ใบ"
        ))
        self.stdout.write("บัญชีทดสอบ (รหัสผ่าน 1234): admin / tech1 / tech2 / user1 / user2")
