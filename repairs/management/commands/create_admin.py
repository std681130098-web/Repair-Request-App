"""
สร้าง/รีเซ็ตบัญชีผู้ดูแลระบบ (superuser) ด้วยรหัสผ่านมาตรฐานของโปรเจกต์.

ใช้สำหรับกรณีที่ได้ไฟล์ Backup.zip ไป แล้วต้องการเข้าหน้า /admin
โดยไม่ต้องรู้รหัสผ่านเดิมของเครื่องที่สำรองมา

ใช้:  python manage.py create_admin
      python manage.py create_admin --all          # รีเซ็ตบัญชีทดสอบทุกบัญชีด้วย
      python manage.py create_admin --password xxx # กำหนดรหัสผ่านเอง

⚠️ รหัสผ่านด้านล่างเป็นค่าสำหรับ "เดโม/การเรียนการสอน" เท่านั้น
   ถ้านำระบบขึ้นใช้งานจริง ต้องเปลี่ยนรหัสผ่านทันทีหลัง login ครั้งแรก
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from repairs.models import User

# --- บัญชีผู้ดูแลระบบมาตรฐานของโปรเจกต์ ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"
ADMIN_EMAIL = "admin@example.com"
ADMIN_NAME = "แอดมิน ใจดี"

# บัญชีทดสอบอื่น ๆ (ใช้กับ --all) — รหัสผ่านเดียวกับ seed_data
DEMO_ACCOUNTS = ["tech1", "tech2", "user1", "user2"]
DEMO_PASSWORD = "1234"


class Command(BaseCommand):
    help = "สร้างหรือรีเซ็ตบัญชีแอดมิน (admin/1234) สำหรับเข้าหน้า /admin"

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", default=ADMIN_PASSWORD,
            help=f"กำหนดรหัสผ่านเอง (ค่าเริ่มต้น: {ADMIN_PASSWORD})",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="รีเซ็ตรหัสผ่านบัญชีทดสอบทั้งหมดด้วย (tech1, tech2, user1, user2)",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        password = opts["password"]

        admin, created = User.objects.get_or_create(
            username=ADMIN_USERNAME,
            defaults=dict(
                first_name=ADMIN_NAME, email=ADMIN_EMAIL,
                role=User.Role.ADMIN, phone="02-111-1111",
            ),
        )
        # รีเซ็ตทุกครั้ง แม้บัญชีจะมีอยู่แล้ว เพื่อให้เข้าได้แน่นอน
        admin.is_staff = True
        admin.is_superuser = True
        admin.is_active = True
        admin.role = User.Role.ADMIN
        admin.set_password(password)
        admin.save()

        verb = "สร้าง" if created else "รีเซ็ตรหัสผ่าน"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}บัญชีแอดมินเรียบร้อย → username: {ADMIN_USERNAME} / password: {password}"
        ))

        if opts["all"]:
            n = 0
            for uname in DEMO_ACCOUNTS:
                u = User.objects.filter(username=uname).first()
                if u:
                    u.set_password(DEMO_PASSWORD)
                    u.is_active = True
                    u.save()
                    n += 1
            self.stdout.write(self.style.SUCCESS(
                f"รีเซ็ตบัญชีทดสอบอีก {n} บัญชี (รหัสผ่าน {DEMO_PASSWORD}): "
                + ", ".join(DEMO_ACCOUNTS)
            ))

        self.stdout.write("เข้าหน้าผู้ดูแลระบบได้ที่ http://127.0.0.1:8000/admin/")
