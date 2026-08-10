"""Template context processors — inject small badge counts into every page."""
from .models import RepairRequest, unread_counts


def pending_counts(request):
    """
    ตัวเลขแจ้งเตือนบนเมนู:
      - admin เห็นจำนวนใบที่ 'รอตรวจสอบ' + 'รอตรวจรับ'
      - ช่างเห็นจำนวนงานที่ยังไม่เสร็จของตัวเอง
      - ทุกบทบาทเห็นจำนวนข้อความสนทนาที่ยังไม่ได้อ่าน (nav_unread)
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    data = {}
    if user.is_admin_role:
        data["nav_admin_todo"] = RepairRequest.objects.filter(
            status__in=[RepairRequest.Status.PENDING, RepairRequest.Status.REVIEW]
        ).count()
    if user.is_technician:
        data["nav_tech_todo"] = RepairRequest.objects.filter(
            assignments__technician=user,
            status__in=[
                RepairRequest.Status.ASSIGNED,
                RepairRequest.Status.IN_PROGRESS,
            ],
        ).distinct().count()

    # ข้อความสนทนาที่ยังไม่ได้อ่าน (รวมทุกใบที่ผู้ใช้เข้าถึงได้)
    reqs = RepairRequest.objects.all()
    if user.is_reporter:
        reqs = reqs.filter(reporter=user)
    elif user.is_technician:
        reqs = reqs.filter(assignments__technician=user).distinct()
    ids = list(reqs.values_list("id", flat=True))
    total_unread = sum(unread_counts(user, ids).values())
    if total_unread:
        data["nav_unread"] = total_unread
    return data
