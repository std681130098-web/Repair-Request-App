"""
Data models for the repair-request system.

Mirrors the ER diagram (5 tables):
  User · Category · RepairRequest · Assignment · Rating
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone


class User(AbstractUser):
    """ผู้ใช้ระบบ — แยกด้วยบทบาท (role) 3 กลุ่ม."""

    class Role(models.TextChoices):
        REPORTER = "reporter", "ผู้แจ้งซ่อม"
        ADMIN = "admin", "ผู้ดูแลระบบ"
        TECHNICIAN = "technician", "ช่างซ่อม"

    role = models.CharField(
        "บทบาท", max_length=20, choices=Role.choices, default=Role.REPORTER
    )
    phone = models.CharField("เบอร์โทรศัพท์", max_length=20, blank=True)

    # --- role helpers ------------------------------------------------------
    @property
    def is_reporter(self):
        return self.role == self.Role.REPORTER

    @property
    def is_admin_role(self):
        # superuser is always treated as an admin as well
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_technician(self):
        return self.role == self.Role.TECHNICIAN

    @property
    def display_name(self):
        full = self.get_full_name()
        return full or self.username

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"


class Category(models.Model):
    """ประเภทงานซ่อม เช่น ไฟฟ้า ประปา คอมพิวเตอร์."""

    name = models.CharField("ชื่อประเภท", max_length=100, unique=True)

    class Meta:
        verbose_name = "ประเภทงานซ่อม"
        verbose_name_plural = "ประเภทงานซ่อม"
        ordering = ["name"]

    def __str__(self):
        return self.name


class RepairRequest(models.Model):
    """ใบแจ้งซ่อม — เอกสารหลักของระบบ."""

    class Status(models.TextChoices):
        PENDING = "pending", "รอตรวจสอบ"
        ASSIGNED = "assigned", "มอบหมายแล้ว"
        IN_PROGRESS = "in_progress", "กำลังดำเนินการ"
        REVIEW = "review", "รอตรวจรับ"
        DONE = "done", "เสร็จสมบูรณ์"
        RETURNED = "returned", "ตีกลับให้แก้ไข"
        CANCELLED = "cancelled", "ยกเลิก"

    # Bootstrap badge colour per status (used by templates).
    STATUS_STYLE = {
        "pending": "secondary",
        "assigned": "info",
        "in_progress": "primary",
        "review": "warning",
        "done": "success",
        "returned": "danger",
        "cancelled": "dark",
    }

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="requests",
        verbose_name="ผู้แจ้งซ่อม",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name="ประเภทงาน",
    )
    title = models.CharField("หัวข้อ / อาการเสีย", max_length=200)
    detail = models.TextField("รายละเอียด", blank=True)
    location = models.CharField("สถานที่", max_length=150, blank=True)
    status = models.CharField(
        "สถานะ", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    admin_note = models.CharField("หมายเหตุจากผู้ดูแล", max_length=255, blank=True)
    created_at = models.DateTimeField("วันที่แจ้ง", default=timezone.now)
    updated_at = models.DateTimeField("อัปเดตล่าสุด", auto_now=True)

    class Meta:
        verbose_name = "ใบแจ้งซ่อม"
        verbose_name_plural = "ใบแจ้งซ่อม"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    def get_absolute_url(self):
        return reverse("request_detail", args=[self.pk])

    # --- convenience -------------------------------------------------------
    @property
    def status_style(self):
        return self.STATUS_STYLE.get(self.status, "secondary")

    @property
    def current_assignment(self):
        """งานมอบหมายล่าสุด (ช่างที่รับผิดชอบตอนนี้)."""
        return self.assignments.order_by("-assigned_date").first()

    @property
    def technician(self):
        a = self.current_assignment
        return a.technician if a else None

    @property
    def has_rating(self):
        return Rating.objects.filter(request=self).exists()

    @property
    def is_open(self):
        return self.status not in (self.Status.DONE, self.Status.CANCELLED)

    @property
    def workflow_steps(self):
        """ลำดับสถานะสำหรับแสดง timeline บนหน้ารายละเอียด."""
        flow = [
            (self.Status.PENDING, "แจ้งซ่อม / รอตรวจสอบ", "bi-pencil-square"),
            (self.Status.ASSIGNED, "มอบหมายช่าง", "bi-person-check"),
            (self.Status.IN_PROGRESS, "กำลังดำเนินการซ่อม", "bi-wrench-adjustable"),
            (self.Status.REVIEW, "รอตรวจรับ", "bi-clipboard-check"),
            (self.Status.DONE, "เสร็จสมบูรณ์", "bi-check-circle"),
        ]
        order = [s[0] for s in flow]
        if self.status == self.Status.CANCELLED:
            cur = -1
        elif self.status == self.Status.RETURNED:
            cur = 0
        else:
            cur = order.index(self.status)
        steps = []
        for i, (val, label, icon) in enumerate(flow):
            state = "done" if i < cur else ("current" if i == cur else "muted")
            steps.append({"label": label, "icon": icon, "state": state})
        return steps


class Assignment(models.Model):
    """การมอบหมายงานให้ช่าง + บันทึกผลการซ่อม."""

    request = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="ใบแจ้งซ่อม",
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jobs",
        limit_choices_to={"role": User.Role.TECHNICIAN},
        verbose_name="ช่างผู้รับผิดชอบ",
    )
    assigned_date = models.DateTimeField("วันที่มอบหมาย", default=timezone.now)
    work_detail = models.TextField("บันทึกการซ่อม", blank=True)
    work_date = models.DateTimeField("วันที่ซ่อมเสร็จ", null=True, blank=True)

    class Meta:
        verbose_name = "การมอบหมายงาน"
        verbose_name_plural = "การมอบหมายงาน"
        ordering = ["-assigned_date"]

    def __str__(self):
        return f"งาน #{self.request_id} → {self.technician.display_name}"


class Rating(models.Model):
    """การประเมินความพึงพอใจ (1 ใบแจ้งซ่อม ประเมินได้ 1 ครั้ง)."""

    SCORE_CHOICES = [(i, f"{i} ดาว") for i in range(1, 6)]

    request = models.OneToOneField(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="rating",
        verbose_name="ใบแจ้งซ่อม",
    )
    score = models.PositiveSmallIntegerField("คะแนน", choices=SCORE_CHOICES, default=5)
    comment = models.CharField("ความคิดเห็น", max_length=255, blank=True)
    created_at = models.DateTimeField("วันที่ประเมิน", default=timezone.now)

    class Meta:
        verbose_name = "การประเมิน"
        verbose_name_plural = "การประเมิน"
        ordering = ["-created_at"]

    def __str__(self):
        return f"ประเมินงาน #{self.request_id}: {self.score}★"

    @property
    def stars(self):
        return "★" * self.score + "☆" * (5 - self.score)
