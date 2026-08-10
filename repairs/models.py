"""
Data models for the repair-request system.

Mirrors the ER diagram (5 tables):
  User · Category · RepairRequest · Assignment · Rating
"""
import os

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
        # ถ้า prefetch_related("assignments") มาแล้ว ใช้แคชเพื่อลดคิวรีในหน้ารายการ
        # (Assignment.Meta.ordering = ["-assigned_date"] → ตัวแรกคือใหม่สุด)
        cache = getattr(self, "_prefetched_objects_cache", None)
        if cache and "assignments" in cache:
            items = list(self.assignments.all())
            return items[0] if items else None
        return self.assignments.order_by("-assigned_date").first()

    @property
    def technician(self):
        a = self.current_assignment
        return a.technician if a else None

    @property
    def has_rating(self):
        return Rating.objects.filter(request=self).exists()

    def comments_for(self, user):
        """ข้อความในเธรดที่ผู้ใช้คนนี้มีสิทธิ์เห็น (ผู้แจ้งไม่เห็นหมายเหตุภายใน)."""
        qs = self.comments.select_related("author")
        if user.is_reporter:
            qs = qs.filter(is_internal=False)
        return qs

    def log_activity(self, actor, text):
        """บันทึกความคืบหน้าอัตโนมัติลงในเธรดสนทนา (ทุกฝ่ายที่เกี่ยวข้องเห็น)."""
        return Comment.objects.create(
            request=self,
            author=actor,
            body=text,
            kind=Comment.Kind.SYSTEM,
            is_internal=False,
        )

    def unread_for(self, user):
        """จำนวนข้อความที่ผู้ใช้คนนี้ยังไม่ได้อ่าน (ไม่นับข้อความของตัวเอง)."""
        return unread_counts(user, [self]).get(self.pk, 0)

    @property
    def report_images(self):
        """รูปที่ผู้แจ้งแนบ (ถ่ายจุดที่ต้องซ่อม)."""
        return self.images.filter(kind=RepairImage.Kind.REPORT)

    @property
    def work_images(self):
        """รูปที่ช่างแนบตอนแจ้งงานเสร็จ."""
        return self.images.filter(kind=RepairImage.Kind.WORK)

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


class RepairImage(models.Model):
    """รูปภาพประกอบใบแจ้งซ่อม — ผู้แจ้งถ่ายจุดที่ต้องซ่อม หรือช่างถ่ายงานที่ซ่อมเสร็จ (แนบได้หลายรูป)."""

    class Kind(models.TextChoices):
        REPORT = "report", "รูปแจ้งซ่อม (ผู้แจ้ง)"
        WORK = "work", "รูปงานเสร็จ (ช่าง)"

    request = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="ใบแจ้งซ่อม",
    )
    kind = models.CharField(
        "ประเภทรูป", max_length=10, choices=Kind.choices, default=Kind.REPORT
    )
    image = models.ImageField("รูปภาพ", upload_to="repairs/%Y/%m")
    caption = models.CharField("คำอธิบายภาพ", max_length=200, blank=True)
    uploaded_at = models.DateTimeField("วันที่อัปโหลด", default=timezone.now)

    class Meta:
        verbose_name = "รูปภาพแจ้งซ่อม"
        verbose_name_plural = "รูปภาพแจ้งซ่อม"
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"รูปของงาน #{self.request_id}"


class Comment(models.Model):
    """ข้อความสนทนาบนใบแจ้งซ่อม — ผู้แจ้ง/แอดมิน/ช่าง คุยและติดตามความคืบหน้า."""

    class Kind(models.TextChoices):
        USER = "user", "ข้อความ"
        SYSTEM = "system", "อัปเดตสถานะงาน"

    request = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="ใบแจ้งซ่อม",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="ผู้เขียน",
    )
    kind = models.CharField(
        "ชนิด", max_length=10, choices=Kind.choices, default=Kind.USER
    )
    body = models.TextField("ข้อความ", blank=True)
    is_internal = models.BooleanField(
        "หมายเหตุภายใน",
        default=False,
        help_text="เห็นเฉพาะผู้ดูแลและช่าง (ผู้แจ้งจะไม่เห็น)",
    )
    created_at = models.DateTimeField("เวลา", default=timezone.now)

    class Meta:
        verbose_name = "ข้อความสนทนา"
        verbose_name_plural = "ข้อความสนทนา"
        ordering = ["created_at"]

    def __str__(self):
        return f"ข้อความของ {self.author} บนงาน #{self.request_id}"

    @property
    def is_system(self):
        """เป็นข้อความอัปเดตสถานะอัตโนมัติ (ไม่ใช่ข้อความที่คนพิมพ์)."""
        return self.kind == self.Kind.SYSTEM


class CommentAttachment(models.Model):
    """ไฟล์/รูปที่แนบมากับข้อความสนทนา (แนบได้หลายไฟล์ต่อข้อความ)."""

    IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="ข้อความ",
    )
    file = models.FileField("ไฟล์แนบ", upload_to="comments/%Y/%m")
    original_name = models.CharField("ชื่อไฟล์เดิม", max_length=255, blank=True)
    uploaded_at = models.DateTimeField("วันที่อัปโหลด", default=timezone.now)

    class Meta:
        verbose_name = "ไฟล์แนบในสนทนา"
        verbose_name_plural = "ไฟล์แนบในสนทนา"
        ordering = ["uploaded_at"]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return self.original_name or os.path.basename(self.file.name)

    @property
    def is_image(self):
        return self.file.name.lower().endswith(self.IMAGE_EXT)

    @property
    def size_display(self):
        try:
            size = self.file.size
        except (ValueError, OSError):
            return ""
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        return f"{max(1, round(size / 1024))} KB"


class ChatRead(models.Model):
    """บันทึกเวลาที่ผู้ใช้เปิดอ่านห้องสนทนาล่าสุด — ใช้คำนวณข้อความที่ยังไม่ได้อ่าน."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_reads",
        verbose_name="ผู้ใช้",
    )
    request = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="chat_reads",
        verbose_name="ใบแจ้งซ่อม",
    )
    last_read_at = models.DateTimeField("อ่านล่าสุดเมื่อ", default=timezone.now)

    class Meta:
        verbose_name = "สถานะการอ่านสนทนา"
        verbose_name_plural = "สถานะการอ่านสนทนา"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "request"], name="uniq_chatread_user_request"
            )
        ]

    def __str__(self):
        return f"{self.user} อ่านงาน #{self.request_id}"


def unread_counts(user, requests):
    """
    คืน dict {request_id: จำนวนข้อความที่ผู้ใช้ยังไม่ได้อ่าน} สำหรับชุดใบแจ้งซ่อมที่ให้มา.

    `requests` เป็น list ของอ็อบเจกต์ RepairRequest หรือ list ของ id ก็ได้.
    นับเฉพาะข้อความที่ผู้ใช้มีสิทธิ์เห็นและไม่ได้เป็นคนเขียนเอง — ใช้เพียง 2 คิวรี.
    """
    ids = [getattr(r, "pk", r) for r in requests]
    if not ids:
        return {}
    reads = dict(
        ChatRead.objects.filter(user=user, request_id__in=ids).values_list(
            "request_id", "last_read_at"
        )
    )
    qs = Comment.objects.filter(request_id__in=ids).exclude(author=user)
    if user.is_reporter:
        qs = qs.filter(is_internal=False)
    counts = {}
    for rid, created in qs.values_list("request_id", "created_at"):
        last = reads.get(rid)
        if last is None or created > last:
            counts[rid] = counts.get(rid, 0) + 1
    return counts


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
