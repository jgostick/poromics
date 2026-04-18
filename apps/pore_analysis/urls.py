from django.urls import path
from . import views

app_name = 'pore_analysis'

# Team-scoped URLs (will be prefixed with /a/<team_slug>/)
team_urlpatterns = (
    [
        path('', views.dashboard, name='dashboard'),
        path('upload/', views.upload_image, name='upload_image'),
        path('images/', views.image_list, name='image_list'),
        path('images/<uuid:image_id>/', views.image_detail, name='image_detail'),
        path('images/<uuid:image_id>/analyze/', views.start_analysis, name='start_analysis'),
        path("images/<uuid:image_id>/delete/", views.delete_image, name="delete_image"),
        path("process-image/", views.process_image, name="process_image"),
        path('jobs/', views.job_list, name='job_list'),
        path('jobs/<uuid:job_id>/', views.job_detail, name='job_detail'),
        path('credits/', views.credit_dashboard, name='credit_dashboard'),
        path("analysis/permeability/", views.permeability_launch, name="permeability_launch"),
        path("trim-image/", views.trim_image, name="trim_image"),
        path("trim-image/preview/", views.trim_image_preview, name="trim_image_preview"),
    ],
    "pore_analysis_team",
)

# Global URLs (no team context needed)
urlpatterns = [
    path('pricing/', views.pricing, name='pricing'),
]
