"""URL patterns for the repairs app."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("signup/", views.signup, name="signup"),

    # requests
    path("requests/", views.request_list, name="request_list"),
    path("requests/new/", views.request_create, name="request_create"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/edit/", views.request_edit, name="request_edit"),
    path("requests/<int:pk>/cancel/", views.request_cancel, name="request_cancel"),
    path("requests/<int:pk>/chat/", views.request_chat, name="request_chat"),
    path("requests/<int:pk>/comment/", views.add_comment, name="add_comment"),
    path("requests/<int:pk>/images/<int:image_id>/delete/", views.image_delete, name="image_delete"),

    # admin actions
    path("requests/<int:pk>/assign/", views.request_assign, name="request_assign"),
    path("requests/<int:pk>/return/", views.request_return, name="request_return"),
    path("requests/<int:pk>/accept/", views.request_accept, name="request_accept"),

    # technician actions
    path("requests/<int:pk>/start/", views.job_start, name="job_start"),
    path("requests/<int:pk>/complete/", views.job_complete, name="job_complete"),

    # reporter action
    path("requests/<int:pk>/rate/", views.request_rate, name="request_rate"),

    # admin console + report
    path("manage/", views.manage, name="manage"),
    path("report/", views.report, name="report"),
]
