"""Django admin registration."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Assignment, Category, Rating, RepairImage, RepairRequest, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "role", "phone", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("บทบาทในระบบแจ้งซ่อม", {"fields": ("role", "phone")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("บทบาทในระบบแจ้งซ่อม", {"fields": ("role", "phone")}),
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0


class RepairImageInline(admin.TabularInline):
    model = RepairImage
    extra = 0


@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "reporter", "category", "status", "created_at")
    list_filter = ("status", "category")
    search_fields = ("title", "detail", "location")
    date_hierarchy = "created_at"
    inlines = [RepairImageInline, AssignmentInline]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "technician", "assigned_date", "work_date")
    list_filter = ("technician",)


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "score", "created_at")
    list_filter = ("score",)
