"""Role-based access control helpers."""
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def role_required(*roles):
    """
    อนุญาตเฉพาะผู้ใช้ที่มีบทบาทตามที่กำหนด (superuser ผ่านได้เสมอ).
    ใช้กับ view function เช่น @role_required("admin").
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect("login")
            if user.is_superuser or user.role in roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, "คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
            raise PermissionDenied("insufficient role")

        return _wrapped

    return decorator


admin_required = role_required("admin")
technician_required = role_required("technician")
reporter_required = role_required("reporter")
