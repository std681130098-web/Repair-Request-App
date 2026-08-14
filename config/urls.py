"""Root URL configuration for the repair-request system."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView  # 💡 เพิ่มการ import ตัวนี้

urlpatterns = [
    # 💡 เพิ่มบรรทัดนี้: ถ้าเปิดหน้าแรก (/) ให้พาไปหน้า /login/ ทันที
    path("", RedirectView.as_view(url="/login/", permanent=False)),
    
    path("django-admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("repairs/", include("repairs.urls")),  # 💡 เปลี่ยน path ของ repairs ไม่ให้ชนกับหน้าแรก
]

# เสิร์ฟไฟล์รูปที่อัปโหลดระหว่างพัฒนา (DEBUG). โปรดักชันให้เว็บเซิร์ฟเวอร์จัดการ
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)