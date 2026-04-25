from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("site-admin/jobs/", views.admin_jobs, name="admin_jobs"),
    path("site-admin/users/", views.admin_users, name="admin_users"),
    path("site-admin/credits/", views.admin_credits, name="admin_credits"),
    path("site-admin/celery/", views.admin_celery, name="admin_celery"),
    path("site-admin/celery/status/", views.admin_celery_status, name="admin_celery_status"),
    path("site-admin/pods/", views.admin_pods, name="admin_pods"),
    path("site-admin/pods/<str:pod_id>/action/", views.admin_pod_action, name="admin_pod_action"),
]
