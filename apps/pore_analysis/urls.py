from django.urls import path
from . import views

app_name = 'pore_analysis'

# Team-scoped URLs (will be prefixed with /a/<team_slug>/)
team_urlpatterns = (
    [
        path('', views.dashboard, name='dashboard'),
        path('upload/', views.upload_image, name='upload_image'),
        path('images/', views.image_list, name='image_list'),
        path('images/refresh-metrics/', views.refresh_image_metrics, name='refresh_image_metrics'),
        path('images/<uuid:image_id>/', views.image_detail, name='image_detail'),
        path('images/<uuid:image_id>/analyze/', views.start_analysis, name='start_analysis'),
        path("images/<uuid:image_id>/delete/", views.delete_image, name="delete_image"),
        path("images/<uuid:image_id>/voxel-size/", views.update_voxel_size, name="update_voxel_size"),
        path("process-image/", views.process_image, name="process_image"),
        path("process-image/load-image/", views.process_image_load_image, name="process_image_load_image"),
        path("process-image/preview/", views.process_image_preview, name="process_image_preview"),
        path("adjust-values/", views.adjust_values, name="adjust_values"),
        path("adjust-values/load-image/", views.adjust_values_load_image, name="adjust_values_load_image"),
        path("adjust-values/preview/", views.adjust_values_preview, name="adjust_values_preview"),
        path('jobs/', views.job_list, name='job_list'),
        path('jobs/<uuid:job_id>/', views.job_detail, name='job_detail'),
        path('credits/', views.credit_dashboard, name='credit_dashboard'),
        path("analysis/permeability/", views.permeability_launch, name="permeability_launch"),
        path("analysis/diffusivity/", views.diffusivity_launch, name="diffusivity_launch"),
        path("trim-image/", views.trim_image, name="trim_image"),
        path("trim-image/load-image/", views.trim_image_load_image, name="trim_image_load_image"),
        path("trim-image/preview/", views.trim_image_preview, name="trim_image_preview"),
        path("analysis/poresize/", views.pore_size_launch, name="poresize_launch"),
    ],
    "pore_analysis_team",
)

# Global URLs (no team context needed)
urlpatterns = [
    path('pricing/', views.pricing, name='pricing'),
]
