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
    CategoryForm,
    CommentForm,
    RatingForm,
    RepairRequestForm,
    ReturnForm,
    SignUpForm,
    WorkLogForm,
)
from .models import (
    Assignment,
    Category,
    ChatRead,
    CommentAttachment,
    RepairImage,
    RepairRequest,
    User,
    unread_counts,
)

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
    else:
        # admin เห็นทุกใบ + มีคอลัมน์ช่าง → prefetch กันคิวรีต่อแถว (N+1)
        qs = qs.prefetch_related("assignments__technician")

    keyword = request.GET.get("q", "").strip()
    if keyword:
        qs = qs.filter(
            Q(title__icontains=keyword)
            | Q(detail__icontains=keyword)
            | Q(location__icontains=keyword)
        )

    # จำนวนงานแต่ละสถานะ (สำหรับชิปตัวกรอง) — นับก่อนกรองสถานะ
    counts = dict(qs.values_list("status").annotate(n=Count("id")))
    total_count = sum(counts.values())

    status = request.GET.get("status", "")
    if status in S.values:
        qs = qs.filter(status=status)

    # แนบจำนวนข้อความที่ยังไม่ได้อ่านของแต่ละใบ (คำนวณครั้งเดียวแบบ batch)
    requests = list(qs)
    umap = unread_counts(user, requests)
    for r in requests:
        r.unread = umap.get(r.pk, 0)

    # ชิปตัวกรอง: ทั้งหมด + เฉพาะสถานะที่มีงาน
    filters = [{"value": "", "label": "ทั้งหมด", "n": total_count}]
    for value, label in S.choices:
        if counts.get(value):
            filters.append({"value": value, "label": label, "n": counts[value]})

    return render(
        request,
        "requests/request_list.html",
        {
            "requests": requests,
            "filters": filters,
            "cur_status": status,
            "keyword": keyword,
        },
    )


# ---------------------------------------------------------------------------
# Create / edit / cancel (reporter)
# ---------------------------------------------------------------------------
def _save_images(req, images, kind=RepairImage.Kind.REPORT):
    """สร้าง RepairImage จากไฟล์รูปที่ผ่านการตรวจแล้ว — คืนจำนวนรูปที่บันทึก."""
    count = 0
    for image in images:
        RepairImage.objects.create(request=req, image=image, kind=kind)
        count += 1
    return count


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
def _can_access_request(user, req):
    """สิทธิ์ดู/สนทนาในใบแจ้งซ่อม: แอดมินทุกใบ · ผู้แจ้งเฉพาะของตน · ช่างเฉพาะที่มอบหมาย."""
    if user.is_admin_role:
        return True
    if user.is_reporter:
        return req.reporter_id == user.id
    if user.is_technician:
        return req.assignments.filter(technician=user).exists()
    return False


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
        "comments": req.comments_for(user),
        # ผู้แจ้ง (เจ้าของ) จัดการรูปได้เฉพาะตอนใบยังแก้ไขได้
        "can_manage_images": (
            user.is_reporter
            and req.reporter_id == user.id
            and req.status in (S.PENDING, S.RETURNED)
        ),
    }
    return render(request, "requests/request_detail.html", ctx)


@login_required
def request_chat(request, pk):
    """ห้องสนทนาแยกของใบแจ้งซ่อม — หน้าเต็มสำหรับพูดคุยและแนบไฟล์."""
    req = get_object_or_404(
        RepairRequest.objects.select_related("reporter", "category"), pk=pk
    )
    user = request.user
    if not _can_access_request(user, req):
        messages.error(request, "คุณไม่มีสิทธิ์เข้าห้องสนทนานี้")
        return redirect("request_list")

    now = timezone.now()
    comments = list(req.comments_for(user).prefetch_related("attachments"))

    # ทำเครื่องหมายว่า "อ่านถึงข้อความล่าสุดที่แสดง" — ใช้เวลาของข้อความใหม่สุดที่โหลดมา
    # (ไม่ใช่ now() หลังโหลด) กันกรณีมีข้อความเข้ามาระหว่างโหลดแล้วถูกนับว่าอ่านทั้งที่ยังไม่เห็น
    newest = max((c.created_at for c in comments), default=now)
    ChatRead.objects.update_or_create(
        user=user, request=req, defaults={"last_read_at": newest}
    )

    return render(
        request,
        "requests/chat.html",
        {
            "req": req,
            "comments": comments,
            "comment_form": CommentForm(),
        },
    )


@login_required
@require_POST
def add_comment(request, pk):
    """ส่งข้อความ + ไฟล์แนบ ในเธรดสนทนา (ผู้แจ้ง/แอดมิน/ช่างที่เกี่ยวข้อง)."""
    req = get_object_or_404(RepairRequest, pk=pk)
    user = request.user
    if not _can_access_request(user, req):
        messages.error(request, "คุณไม่มีสิทธิ์สนทนาในใบแจ้งซ่อมนี้")
        return redirect("request_list")

    form = CommentForm(request.POST, request.FILES)
    if form.is_valid():
        with transaction.atomic():
            comment = form.save(commit=False)
            comment.request = req
            comment.author = user
            if user.is_reporter:
                comment.is_internal = False  # ผู้แจ้งตั้งหมายเหตุภายในไม่ได้
            comment.save()
            for f in form.cleaned_data.get("files", []):
                CommentAttachment.objects.create(
                    comment=comment, file=f, original_name=f.name[:255]
                )
        messages.success(request, "ส่งข้อความแล้ว")
    else:
        first_error = next(iter(form.errors.values()), None)
        messages.error(
            request, first_error[0] if first_error else "ส่งข้อความไม่สำเร็จ"
        )
    return redirect("request_chat", pk=req.pk)


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
        tech = form.cleaned_data["technician"]
        with transaction.atomic():
            Assignment.objects.create(
                request=req,
                technician=tech,
                assigned_date=timezone.now(),
            )
            req.status = S.ASSIGNED
            req.admin_note = form.cleaned_data.get("note", "")
            req.save(update_fields=["status", "admin_note", "updated_at"])
            req.log_activity(request.user, f"มอบหมายงานให้ช่าง {tech.display_name}")
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
        req.log_activity(request.user, f"ตีกลับให้ผู้แจ้งแก้ไข: {reason}")
        messages.info(request, "ตีกลับใบแจ้งซ่อมให้ผู้แจ้งแก้ไขแล้ว")
    elif req.status == S.REVIEW:
        # ตรวจรับไม่ผ่าน ส่งกลับให้ช่างแก้ไข
        req.status = S.IN_PROGRESS
        req.admin_note = reason
        req.save(update_fields=["status", "admin_note", "updated_at"])
        req.log_activity(request.user, f"ส่งงานกลับให้ช่างแก้ไข: {reason}")
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
    req.log_activity(request.user, "ตรวจรับผ่าน — งานเสร็จสมบูรณ์ ✅")
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
    req.log_activity(request.user, "ช่างรับงานแล้ว เริ่มดำเนินการซ่อม 🔧")
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
    form = WorkLogForm(request.POST, request.FILES, instance=assignment)
    if form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.work_date = timezone.now()
            job.save()
            n_imgs = _save_images(
                req, form.cleaned_data.get("images", []), RepairImage.Kind.WORK
            )
            req.status = S.REVIEW
            req.save(update_fields=["status", "updated_at"])
            note = "ช่างแจ้งงานเสร็จ รอผู้ดูแลตรวจรับ 📋"
            if n_imgs:
                note += f" (แนบรูปงาน {n_imgs} รูป)"
            req.log_activity(request.user, note)
        messages.success(request, "บันทึกผลและแจ้งงานเสร็จ รอผู้ดูแลตรวจรับ")
    else:
        # แสดงข้อความ error แรกที่พบ (เช่น รูปเกินจำนวน/ขนาด) ให้ตรงกับสาเหตุจริง
        first_error = next(iter(form.errors.values()), None)
        messages.error(
            request,
            first_error[0] if first_error else "กรุณาบันทึกรายละเอียดการซ่อม",
        )
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
# Admin: management console (คอนโซลจัดการระบบ)
# ---------------------------------------------------------------------------
@admin_required
def manage(request):
    """หน้าจัดการหลักของผู้ดูแล — คิวงาน, ภาระงานช่าง, จัดการประเภทงาน, ผู้ใช้."""
    # เพิ่มประเภทงานซ่อมได้จากหน้านี้เลย
    if request.method == "POST" and "add_category" in request.POST:
        cat_form = CategoryForm(request.POST)
        if cat_form.is_valid():
            cat_form.save()
            messages.success(request, f"เพิ่มประเภทงาน “{cat_form.cleaned_data['name']}” แล้ว")
            return redirect("manage")
        messages.error(request, "เพิ่มประเภทงานไม่สำเร็จ (ชื่ออาจซ้ำหรือว่าง)")
    else:
        cat_form = CategoryForm()

    qs = RepairRequest.objects.all()
    stats = {
        "pending": qs.filter(status=S.PENDING).count(),
        "assigned": qs.filter(status=S.ASSIGNED).count(),
        "in_progress": qs.filter(status=S.IN_PROGRESS).count(),
        "review": qs.filter(status=S.REVIEW).count(),
        "done": qs.filter(status=S.DONE).count(),
        "returned": qs.filter(status=S.RETURNED).count(),
        "cancelled": qs.filter(status=S.CANCELLED).count(),
        "total": qs.count(),
    }

    # คิวงานที่ผู้ดูแลต้องลงมือ
    queue_assign = qs.filter(status=S.PENDING).select_related("reporter", "category").order_by("created_at")
    queue_review = qs.filter(status=S.REVIEW).select_related("reporter", "category").order_by("updated_at")

    # ภาระงานช่างแต่ละคน
    technicians = (
        User.objects.filter(role=User.Role.TECHNICIAN, is_active=True)
        .annotate(
            active_jobs=Count(
                "jobs",
                filter=Q(jobs__request__status__in=[S.ASSIGNED, S.IN_PROGRESS]),
                distinct=True,
            ),
            done_jobs=Count(
                "jobs", filter=Q(jobs__request__status=S.DONE), distinct=True
            ),
        )
        .order_by("-active_jobs", "username")
    )

    categories = Category.objects.annotate(n=Count("requests")).order_by("name")

    people = {
        "reporter": User.objects.filter(role=User.Role.REPORTER).count(),
        "technician": User.objects.filter(role=User.Role.TECHNICIAN).count(),
        "admin": User.objects.filter(role=User.Role.ADMIN).count(),
    }

    avg_rating = RepairRequest.objects.filter(rating__isnull=False).aggregate(
        a=Avg("rating__score")
    )["a"]

    recent = qs.select_related("reporter", "category").order_by("-updated_at")[:8]

    return render(
        request,
        "manage.html",
        {
            "stats": stats,
            "queue_assign": queue_assign,
            "queue_review": queue_review,
            "technicians": technicians,
            "categories": categories,
            "cat_form": cat_form,
            "people": people,
            "avg_rating": avg_rating,
            "recent": recent,
        },
    )


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
