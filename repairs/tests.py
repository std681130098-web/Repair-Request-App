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

from .models import (
    Assignment,
    Category,
    ChatRead,
    Comment,
    Rating,
    RepairImage,
    RepairRequest,
    User,
)

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

    def test_current_assignment_uses_prefetch_cache(self):
        # เมื่อ prefetch_related("assignments") มาแล้ว current_assignment ต้องใช้แคช
        # และยังคืนช่างคนล่าสุดถูกต้อง (กัน N+1 ในหน้ารายการ)
        r = self.new_request(status=S.ASSIGNED)
        Assignment.objects.create(request=r, technician=self.tech)
        fresh = RepairRequest.objects.prefetch_related("assignments__technician").get(pk=r.pk)
        with self.assertNumQueries(0):  # ไม่ยิงคิวรีเพิ่มเพราะใช้แคช
            self.assertEqual(fresh.technician, self.tech)

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


class ManageConsoleTests(BaseData):
    """หน้าคอนโซลจัดการของผู้ดูแล (/manage/)."""

    def test_admin_sees_console_with_queues(self):
        self.new_request(status=S.PENDING)       # เข้า queue_assign
        r = self.new_request(status=S.REVIEW)     # เข้า queue_review
        Assignment.objects.create(request=r, technician=self.tech)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("manage"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["queue_assign"]), 1)
        self.assertEqual(len(resp.context["queue_review"]), 1)
        self.assertContains(resp, "คอนโซลจัดการระบบ")

    def test_reporter_cannot_access_console(self):
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("manage"))
        self.assertEqual(resp.status_code, 403)

    def test_technician_workload_counts(self):
        active = self.new_request(status=S.IN_PROGRESS)
        Assignment.objects.create(request=active, technician=self.tech)
        finished = self.new_request(status=S.DONE)
        Assignment.objects.create(request=finished, technician=self.tech)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("manage"))
        tech = next(t for t in resp.context["technicians"] if t.pk == self.tech.pk)
        self.assertEqual(tech.active_jobs, 1)
        self.assertEqual(tech.done_jobs, 1)

    def test_admin_can_add_category(self):
        self.client.force_login(self.admin)
        before = Category.objects.count()
        resp = self.client.post(reverse("manage"), {"add_category": "1", "name": "ประปา"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Category.objects.count(), before + 1)
        self.assertTrue(Category.objects.filter(name="ประปา").exists())


class CommentThreadTests(BaseData):
    """เธรดสนทนาบนใบแจ้งซ่อม (ผู้แจ้ง/แอดมิน/ช่าง)."""

    def _assigned_request(self):
        r = self.new_request(reporter=self.reporter, status=S.IN_PROGRESS)
        Assignment.objects.create(request=r, technician=self.tech)
        return r

    def test_reporter_and_admin_can_talk(self):
        r = self._assigned_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]), {"body": "อยากทราบความคืบหน้าครับ"})
        self.client.force_login(self.admin)
        self.client.post(reverse("add_comment", args=[r.pk]), {"body": "ช่างกำลังดำเนินการอยู่ครับ"})
        self.assertEqual(r.comments.count(), 2)
        # ทั้งคู่เห็นข้อความของกันและกันในห้องสนทนา
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, "อยากทราบความคืบหน้าครับ")
        self.assertContains(resp, "ช่างกำลังดำเนินการอยู่ครับ")

    def test_internal_note_hidden_from_reporter(self):
        r = self._assigned_request()
        Comment.objects.create(request=r, author=self.admin,
                               body="โน้ตภายในห้ามผู้แจ้งเห็น", is_internal=True)
        Comment.objects.create(request=r, author=self.admin, body="ข้อความปกติ")
        # ผู้แจ้งเห็นเฉพาะข้อความปกติ
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertNotContains(resp, "โน้ตภายในห้ามผู้แจ้งเห็น")
        self.assertContains(resp, "ข้อความปกติ")
        # แอดมินเห็นทั้งหมด
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, "โน้ตภายในห้ามผู้แจ้งเห็น")

    def test_chat_access_denied_for_outsider(self):
        r = self._assigned_request()
        self.client.force_login(self.other)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertEqual(resp.status_code, 302)  # เด้งออกจากห้องสนทนา

    def test_reporter_cannot_post_internal_note(self):
        r = self._assigned_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]),
                         {"body": "พยายามตั้งเป็นภายใน", "is_internal": "on"})
        c = r.comments.get()
        self.assertFalse(c.is_internal)  # ถูกบังคับเป็น False

    def test_outsider_cannot_comment(self):
        r = self._assigned_request()
        self.client.force_login(self.other)  # ผู้แจ้งคนอื่น ไม่ใช่เจ้าของ
        resp = self.client.post(reverse("add_comment", args=[r.pk]), {"body": "แอบเข้ามา"})
        self.assertEqual(resp.status_code, 302)  # ถูกเด้งออก
        self.assertEqual(r.comments.count(), 0)

    def test_empty_comment_rejected(self):
        r = self._assigned_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]), {"body": "   "})
        self.assertEqual(r.comments.count(), 0)

    def test_chat_page_has_composer_enhancements(self):
        # หน้าห้องแชทมีตัวช่วยแนบไฟล์ (chips) และกล่องดูรูปใหญ่ (lightbox)
        r = self._assigned_request()
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, 'id="chat-form"')
        self.assertContains(resp, 'id="file-chips"')
        self.assertContains(resp, 'id="lightbox"')

    def test_system_message_renders_as_activity_line(self):
        r = self._assigned_request()
        r.log_activity(self.admin, "ทดสอบข้อความระบบ")
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, "comment-system")
        self.assertContains(resp, "ทดสอบข้อความระบบ")


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

    # --- ช่างแนบรูปตอนแจ้งงานเสร็จ ----------------------------------------
    def _in_progress_job(self):
        r = self.new_request(status=S.IN_PROGRESS)
        Assignment.objects.create(request=r, technician=self.tech)
        return r

    def test_technician_completes_with_work_images(self):
        r = self._in_progress_job()
        self.client.force_login(self.tech)
        resp = self.client.post(reverse("job_complete", args=[r.pk]), {
            "work_detail": "เปลี่ยนคอมเพรสเซอร์",
            "images": [make_image("done1.png"), make_image("done2.png")],
        })
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.status, S.REVIEW)
        self.assertEqual(r.work_images.count(), 2)
        self.assertEqual(r.report_images.count(), 0)
        # รูปงานเสร็จถูกบันทึกด้วย kind = work
        self.assertTrue(all(i.kind == RepairImage.Kind.WORK for i in r.work_images))

    def test_work_images_shown_separately_from_report_images(self):
        r = self._in_progress_job()
        RepairImage.objects.create(request=r, image=make_image("before.png"),
                                   kind=RepairImage.Kind.REPORT)
        RepairImage.objects.create(request=r, image=make_image("after.png"),
                                   kind=RepairImage.Kind.WORK)
        self.client.force_login(self.admin)
        resp = self.client.get(r.get_absolute_url())
        self.assertContains(resp, "รูปภาพประกอบ")      # แกลเลอรีของผู้แจ้ง
        self.assertContains(resp, "รูปงานที่ซ่อมเสร็จ")  # แกลเลอรีของช่าง

    def test_completing_without_images_still_works(self):
        r = self._in_progress_job()
        self.client.force_login(self.tech)
        self.client.post(reverse("job_complete", args=[r.pk]),
                         {"work_detail": "ขันน็อตให้แน่น"})
        r.refresh_from_db()
        self.assertEqual(r.status, S.REVIEW)
        self.assertEqual(r.work_images.count(), 0)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class ChatAttachmentTests(BaseData):
    """แนบรูป/ไฟล์ในห้องสนทนา."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _my_request(self):
        return self.new_request(reporter=self.reporter, status=S.IN_PROGRESS)

    def test_comment_with_image_and_file(self):
        r = self._my_request()
        pdf = SimpleUploadedFile("report.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        self.client.force_login(self.reporter)
        resp = self.client.post(reverse("add_comment", args=[r.pk]), {
            "body": "แนบรูปกับเอกสารมาให้ครับ",
            "files": [make_image("photo.png"), pdf],
        })
        self.assertEqual(resp.status_code, 302)
        c = r.comments.get()
        self.assertEqual(c.attachments.count(), 2)
        # แยกรูปกับไฟล์เอกสารได้ถูกต้อง
        kinds = {a.is_image for a in c.attachments.all()}
        self.assertEqual(kinds, {True, False})

    def test_attachment_only_comment_allowed(self):
        r = self._my_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]),
                         {"body": "", "files": [make_image("only.png")]})
        self.assertEqual(r.comments.count(), 1)
        self.assertEqual(r.comments.get().attachments.count(), 1)

    def test_empty_body_and_no_file_rejected(self):
        r = self._my_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]), {"body": "   "})
        self.assertEqual(r.comments.count(), 0)

    def test_disallowed_file_type_rejected(self):
        r = self._my_request()
        bad = SimpleUploadedFile("hack.exe", b"MZ...", content_type="application/octet-stream")
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]),
                         {"body": "ไฟล์อันตราย", "files": [bad]})
        self.assertEqual(r.comments.count(), 0)  # ทั้งข้อความถูกปฏิเสธ

    def test_attachments_render_in_chat(self):
        r = self._my_request()
        self.client.force_login(self.reporter)
        self.client.post(reverse("add_comment", args=[r.pk]),
                         {"body": "ดูรูปนี้", "files": [make_image("shown.png")]})
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, "comments/")  # media path ของไฟล์แนบ


# --------------------------------------------------------------------------
class ActivityLogTests(BaseData):
    """บันทึกความคืบหน้าอัตโนมัติในเธรดสนทนา (system messages)."""

    def _pending(self):
        return self.new_request(reporter=self.reporter, status=S.PENDING)

    def test_assign_creates_system_message_visible_to_reporter(self):
        r = self._pending()
        self.client.force_login(self.admin)
        self.client.post(reverse("request_assign", args=[r.pk]), {"technician": self.tech.pk})
        sys = r.comments.filter(kind=Comment.Kind.SYSTEM)
        self.assertEqual(sys.count(), 1)
        self.assertTrue(sys.first().is_system)
        self.assertFalse(sys.first().is_internal)  # ผู้แจ้งต้องเห็นความคืบหน้า
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertContains(resp, "มอบหมายงานให้ช่าง")

    def test_full_workflow_logs_each_step(self):
        r = self._pending()
        self.client.force_login(self.admin)
        self.client.post(reverse("request_assign", args=[r.pk]), {"technician": self.tech.pk})
        self.client.force_login(self.tech)
        self.client.post(reverse("job_start", args=[r.pk]))
        self.client.post(reverse("job_complete", args=[r.pk]), {"work_detail": "ซ่อมเรียบร้อย"})
        self.client.force_login(self.admin)
        self.client.post(reverse("request_accept", args=[r.pk]))
        texts = list(
            r.comments.filter(kind=Comment.Kind.SYSTEM).values_list("body", flat=True)
        )
        self.assertEqual(len(texts), 4)  # assign, start, complete, accept
        self.assertTrue(any("เสร็จสมบูรณ์" in t for t in texts))

    def test_return_reason_is_logged(self):
        r = self._pending()
        self.client.force_login(self.admin)
        self.client.post(reverse("request_return", args=[r.pk]), {"reason": "ข้อมูลไม่ครบ"})
        sys = r.comments.filter(kind=Comment.Kind.SYSTEM).first()
        self.assertIsNotNone(sys)
        self.assertIn("ข้อมูลไม่ครบ", sys.body)

    def test_system_message_counts_toward_reporter_progress(self):
        # ข้อความระบบไม่ใช่หมายเหตุภายใน → ผู้แจ้งเห็นในห้องแชท
        r = self._pending()
        r.log_activity(self.admin, "อัปเดตอัตโนมัติ")
        visible = r.comments_for(self.reporter)
        self.assertEqual(visible.count(), 1)


# --------------------------------------------------------------------------
class UnreadTests(BaseData):
    """ตัวนับข้อความที่ยังไม่ได้อ่าน + การล้างเมื่อเปิดห้องแชท."""

    def _assigned(self):
        r = self.new_request(reporter=self.reporter, status=S.IN_PROGRESS)
        Assignment.objects.create(request=r, technician=self.tech)
        return r

    def test_new_comment_is_unread_for_reporter(self):
        r = self._assigned()
        Comment.objects.create(request=r, author=self.admin, body="อัปเดตให้ทราบ")
        self.assertEqual(r.unread_for(self.reporter), 1)

    def test_own_comment_is_not_unread(self):
        r = self._assigned()
        Comment.objects.create(request=r, author=self.reporter, body="ของฉันเอง")
        self.assertEqual(r.unread_for(self.reporter), 0)

    def test_internal_note_not_unread_for_reporter_but_is_for_tech(self):
        r = self._assigned()
        Comment.objects.create(request=r, author=self.admin, body="ภายใน", is_internal=True)
        self.assertEqual(r.unread_for(self.reporter), 0)
        self.assertEqual(r.unread_for(self.tech), 1)

    def test_opening_chat_clears_unread(self):
        r = self._assigned()
        Comment.objects.create(request=r, author=self.admin, body="มีข้อความใหม่")
        self.assertEqual(r.unread_for(self.reporter), 1)
        self.client.force_login(self.reporter)
        self.client.get(reverse("request_chat", args=[r.pk]))
        self.assertTrue(ChatRead.objects.filter(user=self.reporter, request=r).exists())
        self.assertEqual(r.unread_for(self.reporter), 0)

    def test_read_watermark_uses_newest_shown_comment(self):
        # เปิดห้องแล้ว last_read_at ต้องเท่ากับเวลาข้อความล่าสุดที่แสดง (ไม่ใช่ now())
        r = self._assigned()
        c = Comment.objects.create(request=r, author=self.admin, body="ข้อความล่าสุด")
        self.client.force_login(self.reporter)
        self.client.get(reverse("request_chat", args=[r.pk]))
        cr = ChatRead.objects.get(user=self.reporter, request=r)
        self.assertEqual(cr.last_read_at, c.created_at)

    def test_unread_annotated_on_request_list(self):
        r = self._assigned()
        Comment.objects.create(request=r, author=self.admin, body="ข้อความใหม่")
        self.client.force_login(self.reporter)
        resp = self.client.get(reverse("request_list"))
        row = next(x for x in resp.context["requests"] if x.pk == r.pk)
        self.assertEqual(row.unread, 1)

    def test_request_list_renders_chat_button_for_all_roles(self):
        r = self._assigned()  # เจ้าของ = reporter, ช่าง = tech
        for u in (self.admin, self.tech, self.reporter):
            self.client.force_login(u)
            resp = self.client.get(reverse("request_list"))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "เปิดห้องสนทนา")  # ปุ่มเข้าห้องแชทในตาราง
