"""
Views for the repair-request system.

Implements the flowchart workflow as a small state machine:

  [reporter] แจ้งซ่อม            -> PENDING
  [admin]    มอบหมายช่าง (อนุมัติ) -> ASSIGNED
  [admin]    ตีกลับ               -> RETURNED
  [reporter] แก้ไข/ส่งใหม่         -> PENDING
  [technician] รับงาน/เริ่มซ่อม    -> IN_PROGRESS
  [technician] แจ้งงานเสร็จ        -> REVIEW
  [admin]    ตรวจรับผ่าน           -> DONE
  [admin]    ส่งกลับให้แก้ไข        -> IN_PROGRESS
  [reporter] ประเมินผล             -> (Rating)
"""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import admin_required, role_required
from .forms import (
    AssignForm,
    RatingForm,
    RepairRequestForm,
    ReturnForm,
    SignUpForm,
    WorkLogForm,
)
from .models import Assignment, RepairImage, RepairRequest, User

S = RepairRequest.Status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            user.phone = form.cleaned_data.get("phone", "")
            user.save(update_fields=["phone"])
            login(request, user)
            messages.success(request, "สมัครสมาชิกสำเร็จ ยินดีต้อนรับ!")
            return redirect("dashboard")
    else:
        form = SignUpForm()
    return render(request, "registration/signup.html", {"form": form})


# ---------------------------------------------------------------------------
# Dashboard (role-aware)
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    user = request.user
    ctx = {}

    if user.is_admin_role:
        qs = RepairRequest.objects.all()
        ctx["stats"] = {
            "pending": qs.filter(status=S.PENDING).count(),
            "in_progress": qs.filter(status=S.IN_PROGRESS).count(),
            "review": qs.filter(status=S.REVIEW).count(),
            "done": qs.filter(status=S.DONE).count(),
            "total": qs.count(),
        }
        ctx["todo"] = qs.filter(status__in=[S.PENDING, S.REVIEW]).select_related(
            "reporter", "category"
        )[:8]
        ctx["avg_rating"] = (
            RepairRequest.objects.filter(rating__isnull=False).aggregate(
                a=Avg("rating__score")
            )["a"]
        )
        template = "dashboard_admin.html"

    elif user.is_technician:
        jobs = RepairRequest.objects.filter(assignments__technician=user).distinct()
        ctx["stats"] = {
            "assigned": jobs.filter(status=S.ASSIGNED).count(),
            "in_progress": jobs.filter(status=S.IN_PROGRESS).count(),
            "review": jobs.filter(status=S.REVIEW).count(),
            "done": jobs.filter(status=S.DONE).count(),
        }
        ctx["todo"] = jobs.filter(
            status__in=[S.ASSIGNED, S.IN_PROGRESS]
        ).select_related("reporter", "category").order_by("status", "created_at")
        template = "dashboard_technician.html"

    else:  # reporter
        mine = RepairRequest.objects.filter(reporter=user)
        ctx["stats"] = {
            "open": mine.filter(
                status__in=[S.PENDING, S.ASSIGNED, S.IN_PROGRESS, S.REVIEW]
            ).count(),
            "returned": mine.filter(status=S.RETURNED).count(),
            "done": mine.filter(status=S.DONE).count(),
            "total": mine.count(),
        }
        ctx["recent"] = mine.select_related("category")[:6]
        template = "dashboard_reporter.html"

    return render(request, template, ctx)


# ---------------------------------------------------------------------------
# Request list (scoped by role) + filters
# ---------------------------------------------------------------------------
@login_required
def request_list(request):
    user = request.user
    qs = RepairRequest.objects.select_related("reporter", "category")

    if user.is_reporter:
        qs = qs.filter(reporter=user)
    elif user.is_technician:
        qs = qs.filter(assignments__technician=user).distinct()
    # admin sees everything

    status = request.GET.get("status", "")
    if status in S.values:
        qs = qs.filter(status=status)

    keyword = request.GET.get("q", "").strip()
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword)
            | Q(detail__icontains=keyword)
            | Q(location__icontains=keyword)
        )

    return render(
        request,
        "requests/request_list.html",
        {
            "requests": qs,
            "status_choices": S.choices,
            "cur_status": status,
            "keyword": keyword,
        },
    )


# ---------------------------------------------------------------------------
# Create / edit / cancel (reporter)
# ---------------------------------------------------------------------------
def _save_images(req, images):
    """สร้าง RepairImage จากไฟล์รูปที่ผ่านการตรวจแล้ว."""
    for image in images:
        RepairImage.objects.create(request=req, image=image)


@role_required("reporter")
def request_create(request):
    if request.method == "POST":
        form = RepairRequestForm(request.POST, request.FILES)
        if form.is_valid():
            req = form.save(commit=False)
            req.reporter = request.user
            req.status = S.PENDING
            req.save()
            _save_images(req, form.cleaned_data.get("images", []))
            messages.success(request, f"ส่งใบแจ้งซ่อม #{req.pk} เรียบร้อยแล้ว")
            return redirect(req.get_absolute_url())
    else:
        form = RepairRequestForm()
    return render(request, "requests/request_form.html", {"form": form, "mode": "create"})


@role_required("reporter")
def request_edit(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk, reporter=request.user)
    if req.status not in (S.PENDING, S.RETURNED):
        messages.error(request, "แก้ไขได้เฉพาะใบที่รอตรวจสอบหรือถูกตีกลับเท่านั้น")
        return redirect(req.get_absolute_url())
    if request.method == "POST":
        form = RepairRequestForm(request.POST, request.FILES, instance=req)
        if form.is_valid():
            req = form.save(commit=False)
            was_returned = req.status == S.RETURNED
            req.status = S.PENDING  # แก้ไขแล้วส่งกลับเข้าคิวตรวจสอบ
            req.admin_note = "" if was_returned else req.admin_note
            req.save()
            _save_images(req, form.cleaned_data.get("images", []))
            messages.success(request, "บันทึกการแก้ไขและส่งกลับให้ตรวจสอบแล้ว")
            return redirect(req.get_absolute_url())
    else:
        form = RepairRequestForm(instance=req)
    return render(
        request, "requests/request_form.html", {"form": form, "mode": "edit", "req": req}
    )


@role_required("reporter")
@require_POST
def image_delete(request, pk, image_id):
    """ผู้แจ้งลบรูปของตัวเอง — เฉพาะใบที่ยังแก้ไขได้ (รอตรวจสอบ/ถูกตีกลับ)."""
    req = get_object_or_404(RepairRequest, pk=pk, reporter=request.user)
    if req.status not in (S.PENDING, S.RETURNED):
        messages.error(request, "ลบรูปได้เฉพาะใบที่ยังไม่ถูกดำเนินการเท่านั้น")
        return redirect(req.get_absolute_url())
    image = get_object_or_404(RepairImage, pk=image_id, request=req)
    image.image.delete(save=False)  # ลบไฟล์ออกจากดิสก์
    image.delete()
    messages.info(request, "ลบรูปแล้ว")
    return redirect(req.get_absolute_url())


@role_required("reporter")
@require_POST
def request_cancel(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk, reporter=request.user)
    if req.status in (S.PENDING, S.RETURNED):
        req.status = S.CANCELLED
        req.save(update_fields=["status", "updated_at"])
        messages.info(request, f"ยกเลิกใบแจ้งซ่อม #{req.pk} แล้ว")
    else:
        messages.error(request, "ไม่สามารถยกเลิกใบที่กำลังดำเนินการได้")
    return redirect(req.get_absolute_url())


# ---------------------------------------------------------------------------
# Detail (dispatches all the action buttons)
# ---------------------------------------------------------------------------
@login_required
def request_detail(request, pk):
    req = get_object_or_404(
        RepairRequest.objects.select_related("reporter", "category"), pk=pk
    )
    user = request.user

    # access control: reporter only own; technician only assigned; admin all
    if user.is_reporter and req.reporter_id != user.id:
        messages.error(request, "คุณไม่มีสิทธิ์ดูใบแจ้งซ่อมนี้")
        return redirect("request_list")
    if user.is_technician and not req.assignments.filter(technician=user).exists():
        messages.error(request, "งานนี้ไม่ได้มอบหมายให้คุณ")
        return redirect("request_list")

    assignment = req.current_assignment
    ctx = {
        "req": req,
        "assignment": assignment,
        "assign_form": AssignForm(),
        "return_form": ReturnForm(),
        "worklog_form": WorkLogForm(instance=assignment),
        "rating_form": RatingForm(),
        # ผู้แจ้ง (เจ้าของ) จัดการรูปได้เฉพาะตอนใบยังแก้ไขได้
        "can_manage_images": (
            user.is_reporter
            and req.reporter_id == user.id
            and req.status in (S.PENDING, S.RETURNED)
        ),
    }
    return render(request, "requests/request_detail.html", ctx)


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------
@admin_required
@require_POST
def request_assign(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk)
    if req.status not in (S.PENDING, S.RETURNED):
        messages.error(request, "มอบหมายได้เฉพาะใบที่รอตรวจสอบเท่านั้น")
        return redirect(req.get_absolute_url())
    form = AssignForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            Assignment.objects.create(
                request=req,
                technician=form.cleaned_data["technician"],
                assigned_date=timezone.now(),
            )
            req.status = S.ASSIGNED
            req.admin_note = form.cleaned_data.get("note", "")
            req.save(update_fields=["status", "admin_note", "updated_at"])
        messages.success(
            request,
            f"มอบหมายงาน #{req.pk} ให้ {form.cleaned_data['technician'].display_name} แล้ว",
        )
    else:
        messages.error(request, "กรุณาเลือกช่างให้ถูกต้อง")
    return redirect(req.get_absolute_url())


@admin_required
@require_POST
def request_return(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk)
    form = ReturnForm(request.POST)
    if not form.is_valid():
        messages.error(request, "กรุณาระบุเหตุผลในการตีกลับ")
        return redirect(req.get_absolute_url())
    reason = form.cleaned_data["reason"]

    if req.status == S.PENDING:
        # ตีกลับคำร้องให้ผู้แจ้งแก้ไข
        req.status = S.RETURNED
        req.admin_note = reason
        req.save(update_fields=["status", "admin_note", "updated_at"])
        messages.info(request, "ตีกลับใบแจ้งซ่อมให้ผู้แจ้งแก้ไขแล้ว")
    elif req.status == S.REVIEW:
        # ตรวจรับไม่ผ่าน ส่งกลับให้ช่างแก้ไข
        req.status = S.IN_PROGRESS
        req.admin_note = reason
        req.save(update_fields=["status", "admin_note", "updated_at"])
        messages.info(request, "ส่งงานกลับให้ช่างแก้ไขแล้ว")
    else:
        messages.error(request, "สถานะปัจจุบันไม่สามารถตีกลับได้")
    return redirect(req.get_absolute_url())


@admin_required
@require_POST
def request_accept(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk)
    if req.status != S.REVIEW:
        messages.error(request, "ตรวจรับได้เฉพาะงานที่รอตรวจรับเท่านั้น")
        return redirect(req.get_absolute_url())
    req.status = S.DONE
    req.save(update_fields=["status", "updated_at"])
    messages.success(request, f"ตรวจรับงาน #{req.pk} เรียบร้อย งานเสร็จสมบูรณ์")
    return redirect(req.get_absolute_url())


# ---------------------------------------------------------------------------
# Technician actions
# ---------------------------------------------------------------------------
@role_required("technician")
@require_POST
def job_start(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk)
    if not req.assignments.filter(technician=request.user).exists():
        messages.error(request, "งานนี้ไม่ได้มอบหมายให้คุณ")
        return redirect("request_list")
    if req.status != S.ASSIGNED:
        messages.error(request, "เริ่มงานได้เฉพาะงานที่เพิ่งมอบหมายเท่านั้น")
        return redirect(req.get_absolute_url())
    req.status = S.IN_PROGRESS
    req.save(update_fields=["status", "updated_at"])
    messages.success(request, "รับงานแล้ว เริ่มดำเนินการซ่อม")
    return redirect(req.get_absolute_url())


@role_required("technician")
@require_POST
def job_complete(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk)
    assignment = req.current_assignment
    if not assignment or assignment.technician_id != request.user.id:
        messages.error(request, "งานนี้ไม่ได้มอบหมายให้คุณ")
        return redirect("request_list")
    if req.status != S.IN_PROGRESS:
        messages.error(request, "แจ้งเสร็จได้เฉพาะงานที่กำลังดำเนินการเท่านั้น")
        return redirect(req.get_absolute_url())
    form = WorkLogForm(request.POST, instance=assignment)
    if form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.work_date = timezone.now()
            job.save()
            req.status = S.REVIEW
            req.save(update_fields=["status", "updated_at"])
        messages.success(request, "บันทึกผลและแจ้งงานเสร็จ รอผู้ดูแลตรวจรับ")
    else:
        messages.error(request, "กรุณาบันทึกรายละเอียดการซ่อม")
    return redirect(req.get_absolute_url())


# ---------------------------------------------------------------------------
# Reporter: rating
# ---------------------------------------------------------------------------
@role_required("reporter")
@require_POST
def request_rate(request, pk):
    req = get_object_or_404(RepairRequest, pk=pk, reporter=request.user)
    if req.status != S.DONE:
        messages.error(request, "ประเมินได้เฉพาะงานที่เสร็จสมบูรณ์แล้ว")
        return redirect(req.get_absolute_url())
    if req.has_rating:
        messages.info(request, "ใบแจ้งซ่อมนี้ถูกประเมินไปแล้ว")
        return redirect(req.get_absolute_url())
    form = RatingForm(request.POST)
    if form.is_valid():
        rating = form.save(commit=False)
        rating.request = req
        rating.save()
        messages.success(request, "ขอบคุณสำหรับการประเมิน!")
    else:
        messages.error(request, "กรุณาให้คะแนนความพึงพอใจ")
    return redirect(req.get_absolute_url())


# ---------------------------------------------------------------------------
# Admin: simple report page
# ---------------------------------------------------------------------------
@admin_required
def report(request):
    by_status = (
        RepairRequest.objects.values("status")
        .annotate(n=Count("id"))
        .order_by()
    )
    status_map = {row["status"]: row["n"] for row in by_status}
    status_rows = [
        {"label": label, "value": value, "n": status_map.get(value, 0),
         "style": RepairRequest.STATUS_STYLE.get(value, "secondary")}
        for value, label in S.choices
    ]

    by_category = (
        RepairRequest.objects.values("category__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    by_tech = (
        Assignment.objects.values("technician__first_name", "technician__username")
        .annotate(n=Count("id"), done=Count("id", filter=Q(request__status=S.DONE)))
        .order_by("-n")
    )
    avg_rating = RepairRequest.objects.filter(rating__isnull=False).aggregate(
        a=Avg("rating__score")
    )["a"]

    return render(
        request,
        "report.html",
        {
            "status_rows": status_rows,
            "by_category": by_category,
            "by_tech": by_tech,
            "avg_rating": avg_rating,
            "total": RepairRequest.objects.count(),
        },
    )
