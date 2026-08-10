"""
Django admin registration.

ปรับแต่งให้ผู้ดูแลระบบใช้งานง่ายและเข้าใจบริบทของ "ระบบแจ้งซ่อม":
เปลี่ยนหัวเว็บเป็นภาษาไทย, ป้ายสถานะแบบมีสี, แสดงรูปย่อ,
คอลัมน์/ตัวกรอง/ช่องค้นหาที่ตรงกับงานจริง.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import (
    Assignment,
    Category,
    Comment,
    CommentAttachment,
    Rating,
    RepairImage,
    RepairRequest,
    User,
)

# --- Branding ของหน้า admin ------------------------------------------------
admin.site.site_header = "ระบบแจ้งซ่อมออนไลน์ · หลังบ้าน"
admin.site.site_title = "ระบบแจ้งซ่อม"
admin.site.index_title = "เมนูจัดการข้อมูล"

# สีป้ายสถานะ (ตรงกับ Bootstrap badge บนหน้าเว็บผู้ใช้)
_STATUS_COLOR = {
    "pending": "#6c757d",
    "assigned": "#0dcaf0",
    "in_progress": "#0d6efd",
    "review": "#ffc107",
    "done": "#198754",
    "returned": "#dc3545",
    "cancelled": "#212529",
}


def _status_badge(obj):
    """ป้ายสถานะสีสำหรับใช้ในหลายหน้า admin."""
    color = _STATUS_COLOR.get(obj.status, "#6c757d")
    return format_html(
        '<span style="background:{};color:#fff;padding:2px 10px;'
        'border-radius:10px;font-size:12px;white-space:nowrap">{}</span>',
        color,
        obj.get_status_display(),
    )


# ---------------------------------------------------------------------------
# ผู้ใช้ระบบ
# ---------------------------------------------------------------------------
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "role_badge", "phone", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "first_name", "phone")
    ordering = ("role", "username")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("บทบาทในระบบแจ้งซ่อม", {"fields": ("role", "phone")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("บทบาทในระบบแจ้งซ่อม", {"fields": ("role", "phone")}),
    )

    @admin.display(description="บทบาท", ordering="role")
    def role_badge(self, obj):
        colors = {"admin": "#0d6efd", "technician": "#198754", "reporter": "#6c757d"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:10px;font-size:12px">{}</span>',
            colors.get(obj.role, "#6c757d"),
            obj.get_role_display(),
        )


# ---------------------------------------------------------------------------
# ประเภทงานซ่อม
# ---------------------------------------------------------------------------
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "request_count")
    search_fields = ("name",)

    @admin.display(description="จำนวนใบแจ้งซ่อม")
    def request_count(self, obj):
        return obj.requests.count()


# ---------------------------------------------------------------------------
# Inlines สำหรับหน้าใบแจ้งซ่อม
# ---------------------------------------------------------------------------
class RepairImageInline(admin.TabularInline):
    model = RepairImage
    extra = 0
    fields = ("thumb", "kind", "image", "caption", "uploaded_at")
    readonly_fields = ("thumb", "uploaded_at")

    @admin.display(description="ตัวอย่าง")
    def thumb(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:6px;'
                'object-fit:cover" />',
                obj.image.url,
            )
        return "—"


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    fields = ("technician", "assigned_date", "work_detail", "work_date")


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("author", "body", "is_internal", "created_at")
    readonly_fields = ("created_at",)


# ---------------------------------------------------------------------------
# ใบแจ้งซ่อม (เอกสารหลัก)
# ---------------------------------------------------------------------------
@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "reporter", "category",
        "status_col", "technician_col", "image_count", "created_at",
    )
    list_display_links = ("id", "title")
    list_filter = ("status", "category", "created_at")
    search_fields = ("title", "detail", "location", "reporter__username", "reporter__first_name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("reporter", "category")
    list_per_page = 25
    save_on_top = True
    autocomplete_fields = ("reporter", "category")
    readonly_fields = ("created_at", "updated_at")
    inlines = [RepairImageInline, AssignmentInline, CommentInline]
    fieldsets = (
        ("ข้อมูลใบแจ้งซ่อม", {"fields": ("reporter", "category", "title", "detail", "location")}),
        ("สถานะการดำเนินการ", {"fields": ("status", "admin_note")}),
        ("เวลา", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="สถานะ", ordering="status")
    def status_col(self, obj):
        return _status_badge(obj)

    @admin.display(description="ช่างผู้รับผิดชอบ")
    def technician_col(self, obj):
        tech = obj.technician
        return tech.display_name if tech else "—"

    @admin.display(description="รูป")
    def image_count(self, obj):
        n_report = obj.images.filter(kind=RepairImage.Kind.REPORT).count()
        n_work = obj.images.filter(kind=RepairImage.Kind.WORK).count()
        return format_html(
            '<span title="รูปแจ้ง / รูปงานเสร็จ">📷 {} · 🔧 {}</span>', n_report, n_work
        )


# ---------------------------------------------------------------------------
# การมอบหมายงาน
# ---------------------------------------------------------------------------
@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "technician", "assigned_date", "work_date", "is_done")
    list_filter = ("technician", "assigned_date")
    search_fields = ("request__title", "technician__username", "technician__first_name")
    date_hierarchy = "assigned_date"
    autocomplete_fields = ("request", "technician")

    @admin.display(description="ซ่อมเสร็จแล้ว", boolean=True)
    def is_done(self, obj):
        return obj.work_date is not None


# ---------------------------------------------------------------------------
# การประเมิน
# ---------------------------------------------------------------------------
class CommentAttachmentInline(admin.TabularInline):
    model = CommentAttachment
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "author", "kind", "preview", "is_internal", "created_at")
    list_filter = ("kind", "is_internal", "created_at")
    search_fields = ("body", "request__title", "author__username")
    date_hierarchy = "created_at"
    autocomplete_fields = ("request", "author")
    inlines = [CommentAttachmentInline]

    @admin.display(description="ข้อความ")
    def preview(self, obj):
        return (obj.body[:40] + "…") if len(obj.body) > 40 else (obj.body or "(ไฟล์แนบ)")


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "stars_col", "comment", "created_at")
    list_filter = ("score", "created_at")
    search_fields = ("request__title", "comment")
    date_hierarchy = "created_at"

    @admin.display(description="คะแนน", ordering="score")
    def stars_col(self, obj):
        return format_html('<span style="color:#f0a500;font-size:15px">{}</span>', obj.stars)
