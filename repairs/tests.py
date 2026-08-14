"""
Automated tests for the repair-request system.

Run:  python manage.py test
Covers: models, role-based access control, and the full workflow state machine.
"""
import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Assignment, Category, Rating, RepairImage, RepairRequest, User

S = RepairRequest.Status


def make_image(name="test.png", size=(12, 12), color="red"):
    """สร้างไฟล์รูปจริงในหน่วยความจำสำหรับทดสอบการอัปโหลด."""
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


def make_user(username, role, **kw):
    u = User(username=username, role=role, first_name=username.title(), **kw)
    u.set_password("1234")
    u.save()
    return u


class BaseData(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin", User.Role.ADMIN, is_staff=True, is_superuser=True)
        cls.tech = make_user("tech1", User.Role.TECHNICIAN)
        cls.tech2 = make_user("tech2", User.Role.TECHNICIAN)
        cls.reporter = make_user("user1", User.Role.REPORTER)
        cls.other = make_user("user2", User.Role.REPORTER)
        cls.cat = Category.objects.create(name="ไฟฟ้า")

    def new_request(self, reporter=None, status=S.PENDING):
        return RepairRequest.objects.create(
            reporter=reporter or self.reporter, category=self.cat,
            title="แอร์เสีย", status=status,
        )


# --------------------------------------------------------------------------
class ModelTests(BaseData):
    def test_role_helpers(self):
        self.assertTrue(self.reporter.is_reporter)
        self.assertTrue(self.tech.is_technician)
        self.assertTrue(self.admin.is_admin_role)
        # superuser without admin role still counts as admin
        su = make_user("root", User.Role.REPORTER, is_superuser=True)
        self.assertTrue(su.is_admin_role)

    def test_status_style(self):
        r = self.new_request()
        self.assertEqual(r.status_style, "secondary")
        r.status = S.DONE
        self.assertEqual(r.status_style, "success")

    def test_technician_property_follows_latest_assignment(self):
        r = self.new_request(status=S.ASSIGNED)
        Assignment.objects.create(request=r, technician=self.tech)
        self.assertEqual(r.technician, self.tech)

    def test_workflow_steps_marks_current(self):
        r = self.new_request(status=S.IN_PROGRESS)
        states = [s["state"] for s in r.workflow_steps]
        # PENDING, ASSIGNED done; IN_PROGRESS current; REVIEW, DONE muted
        self.assertEqual(states, ["done", "done", "current", "muted", "muted"])

    def test_rating_one_to_one(self):
        r = self.new_request(status=S.DONE)
        Rating.objects.create(request=r, score=4)
        self.assertTrue(r.has_rating)
        self.assertEqual(r.rating.stars, "★★★★☆")


# --------------------------------------------------------------------------
class AccessControlTests(BaseData):
    def test_login_required(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_reporter_cannot_view_others_request(self):
        r = self.new_request(reporter=self.other)
        self.client.force_login(self.reporter)
        resp = self.client.get(r.get_absolute_url(), follow=True)
        # redirected away from the detail page
        self.assertNotContains(resp, "แอร์เสีย")

    def test_technician_cannot_view_unassigned(self):
        r = self.new_request(status=S.PENDING)
        self.client.force_login(self.tech)
        resp = self.client.get(r.get_absolute_url(), follow=True)
        self.assertNotContains(resp, "แอร์เสีย")

    def test_reporter_cannot_assign(self):
        r = self.new_request()
        self.client.force_login(self.reporter)
        resp = self.client.post(
            reverse("request_assign", args=[r.pk]), {"technician": self.tech.pk}
        )
        self.assertEqual(resp.status_code, 403)
        r.refresh_from_db()
        self.assertEqual(r.status, S.PENDING)

    def test_technician_cannot_accept(self):
        r = self.new_request(status=S.REVIEW)
        self.client.force_login(self.tech)
        resp = self.client.post(reverse("request_accept", args=[r.pk]))
        self.assertEqual(resp.status_code, 403)


# --------------------------------------------------------------------------
class WorkflowTests(BaseData):
    def test_reporter_creates_request(self):
        self.client.force_login(self.reporter)
        resp = self.client.post(
            reverse("request_create"),
            {"category": self.cat.pk, "title": "ไฟดับ", "detail": "x", "location": "ชั้น 1"},
        )
        self.assertEqual(resp.status_code, 302)
        req = RepairRequest.objects.get(title="ไฟดับ")
        self.assertEqual(req.reporter, self.reporter)
        self.assertEqual(req.status, S.PENDING)

    def test_full_happy_path(self):
        r = self.new_request()

        # admin assigns
        self.client.force_login(self.admin)
        self.client.post(reverse("request_assign", args=[r.pk]),
                         {"technician": self.tech.pk, "note": "ด่วน"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.ASSIGNED)
        self.assertEqual(r.technician, self.tech)

        # technician starts
        self.client.force_login(self.tech)
        self.client.post(reverse("job_start", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, S.IN_PROGRESS)

        # technician completes with a work log
        self.client.post(reverse("job_complete", args=[r.pk]),
                         {"work_detail": "เปลี่ยนอะไหล่แล้ว"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.REVIEW)
        self.assertEqual(r.current_assignment.work_detail, "เปลี่ยนอะไหล่แล้ว")
        self.assertIsNotNone(r.current_assignment.work_date)

        # admin accepts
        self.client.force_login(self.admin)
        self.client.post(reverse("request_accept", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, S.DONE)

        # reporter rates
        self.client.force_login(self.reporter)
        self.client.post(reverse("request_rate", args=[r.pk]),
                         {"score": 5, "comment": "ดีมาก"})
        r.refresh_from_db()
        self.assertTrue(r.has_rating)
        self.assertEqual(r.rating.score, 5)

    def test_admin_return_then_reporter_edit(self):
        r = self.new_request()
        self.client.force_login(self.admin)
        self.client.post(reverse("request_return", args=[r.pk]),
                         {"reason": "ข้อมูลไม่ครบ"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.RETURNED)
        self.assertEqual(r.admin_note, "ข้อมูลไม่ครบ")

        # reporter edits -> back to pending, note cleared
        self.client.force_login(self.reporter)
        self.client.post(reverse("request_edit", args=[r.pk]),
                         {"category": self.cat.pk, "title": "แอร์เสีย (แก้ไข)",
                          "detail": "เพิ่มข้อมูล", "location": "อาคาร 2 ห้อง 201"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.PENDING)
        self.assertEqual(r.admin_note, "")

    def test_return_on_already_returned_request_is_rejected(self):
        # ใบที่ถูกตีกลับแล้ว ตีกลับซ้ำไม่ได้ (สถานะต้องไม่เปลี่ยน)
        r = self.new_request(status=S.RETURNED)
        self.client.force_login(self.admin)
        self.client.post(reverse("request_return", args=[r.pk]),
                         {"reason": "อีกรอบ"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.RETURNED)  # unchanged, no dead-end transition

    def test_detail_hides_return_button_for_returned_request(self):
        # admin ไม่ควรเห็นปุ่ม "ตีกลับ" บนใบที่ตีกลับไปแล้ว แต่ยังมอบหมายได้
        r = self.new_request(status=S.RETURNED)
        self.client.force_login(self.admin)
        resp = self.client.get(r.get_absolute_url())
        self.assertContains(resp, reverse("request_assign", args=[r.pk]))
        self.assertNotContains(resp, reverse("request_return", args=[r.pk]))
        # ส่วนใบที่รอตรวจสอบยังต้องมีปุ่มตีกลับตามปกติ
        pending = self.new_request(status=S.PENDING)
        resp2 = self.client.get(pending.get_absolute_url())
        self.assertContains(resp2, reverse("request_return", args=[pending.pk]))

    def test_review_return_goes_back_to_technician(self):
        r = self.new_request(status=S.REVIEW)
        Assignment.objects.create(request=r, technician=self.tech)
        self.client.force_login(self.admin)
        self.client.post(reverse("request_return", args=[r.pk]),
                         {"reason": "ยังซ่อมไม่เรียบร้อย"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.IN_PROGRESS)

    def test_cannot_start_someone_elses_job(self):
        r = self.new_request(status=S.ASSIGNED)
        Assignment.objects.create(request=r, technician=self.tech)
        self.client.force_login(self.tech2)  # different technician
        self.client.post(reverse("job_start", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, S.ASSIGNED)  # unchanged

    def test_cannot_rate_before_done(self):
        r = self.new_request(status=S.IN_PROGRESS)
        self.client.force_login(self.reporter)
        self.client.post(reverse("request_rate", args=[r.pk]), {"score": 5})
        self.assertFalse(r.has_rating)

    def test_reporter_can_cancel_pending(self):
        r = self.new_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("request_cancel", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.status, S.CANCELLED)

    def test_list_scoping_for_reporter(self):
        mine = self.new_request(reporter=self.reporter)
        theirs = self.new_request(reporter=self.other)
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_list"))
        ids = {r.pk for r in resp.context["requests"]}
        self.assertIn(mine.pk, ids)
        self.assertNotIn(theirs.pk, ids)


# --------------------------------------------------------------------------
_TEST_MEDIA = tempfile.mkdtemp(prefix="repair_test_media_")


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class ImageUploadTests(BaseData):
    """แนบรูป / แสดง / ลบ รูปภาพประกอบใบแจ้งซ่อม."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_create_with_images(self):
        self.client.force_login(self.reporter)
        resp = self.client.post(reverse("request_create"), {
            "category": self.cat.pk, "title": "หลอดไฟเสีย", "detail": "x",
            "location": "ห้อง 101",
            "images": [make_image("a.png"), make_image("b.png")],
        })
        self.assertEqual(resp.status_code, 302)
        req = RepairRequest.objects.get(title="หลอดไฟเสีย")
        self.assertEqual(req.images.count(), 2)

    def test_images_render_on_detail(self):
        req = self.new_request()
        RepairImage.objects.create(request=req, image=make_image("show.png"))
        self.client.force_login(self.reporter)
        resp = self.client.get(req.get_absolute_url())
        self.assertContains(resp, "รูปภาพประกอบ")
        self.assertContains(resp, "repairs/")  # media path of the uploaded file

    def test_reporter_deletes_own_image_when_editable(self):
        req = self.new_request(status=S.RETURNED)
        img = RepairImage.objects.create(request=req, image=make_image("del.png"))
        self.client.force_login(self.reporter)
        resp = self.client.post(
            reverse("image_delete", args=[req.pk, img.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(RepairImage.objects.filter(pk=img.pk).exists())

    def test_cannot_delete_image_once_in_progress(self):
        req = self.new_request(status=S.IN_PROGRESS)
        img = RepairImage.objects.create(request=req, image=make_image("keep.png"))
        self.client.force_login(self.reporter)
        self.client.post(reverse("image_delete", args=[req.pk, img.pk]))
        self.assertTrue(RepairImage.objects.filter(pk=img.pk).exists())

    def test_other_reporter_cannot_delete_image(self):
        req = self.new_request(reporter=self.reporter, status=S.PENDING)
        img = RepairImage.objects.create(request=req, image=make_image("mine.png"))
        self.client.force_login(self.other)  # different reporter
        resp = self.client.post(reverse("image_delete", args=[req.pk, img.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(RepairImage.objects.filter(pk=img.pk).exists())

    def test_non_image_file_is_rejected(self):
        self.client.force_login(self.reporter)
        bad = SimpleUploadedFile("evil.txt", b"not an image", content_type="text/plain")
        self.client.post(reverse("request_create"), {
            "category": self.cat.pk, "title": "ไฟล์แปลก", "detail": "x",
            "location": "y", "images": [bad],
        })
        self.assertFalse(RepairRequest.objects.filter(title="ไฟล์แปลก").exists())
        self.assertEqual(RepairImage.objects.count(), 0)

    def test_too_many_images_rejected(self):
        self.client.force_login(self.reporter)
        imgs = [make_image(f"{i}.png") for i in range(6)]  # เกิน 5
        self.client.post(reverse("request_create"), {
            "category": self.cat.pk, "title": "รูปเยอะ", "detail": "x",
            "location": "y", "images": imgs,
        })
        self.assertFalse(RepairRequest.objects.filter(title="รูปเยอะ").exists())
