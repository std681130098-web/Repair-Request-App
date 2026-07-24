"""Root URL configuration for the repair-request system."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("repairs.urls")),
]

# เสิร์ฟไฟล์รูปที่อัปโหลดระหว่างพัฒนา (DEBUG). โปรดักชันให้เว็บเซิร์ฟเวอร์จัดการ
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
