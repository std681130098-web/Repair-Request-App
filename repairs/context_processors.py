"""Template context processors — inject small badge counts into every page."""
from .models import RepairRequest


def pending_counts(request):
    """
    ตัวเลขแจ้งเตือนบนเมนู:
      - admin เห็นจำนวนใบที่ 'รอตรวจสอบ' + 'รอตรวจรับ'
      - ช่างเห็นจำนวนงานที่ยังไม่เสร็จของตัวเอง
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
    return data
