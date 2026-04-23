from django.contrib import admin

from .models import AnalysisJob, AnalysisResult, CreditTransaction, UploadedImage


@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ["name", "uploaded_by", "team", "file_size_mb", "created_at"]
    list_filter = ["team", "created_at", "uploaded_by"]
    search_fields = ["name", "description", "uploaded_by__email"]
    readonly_fields = ["id", "file_size", "dimensions", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("name", "description", "file", "uploaded_by", "team")}),
        ("Metadata", {"fields": ("dimensions", "voxel_size", "file_size"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ["image", "analysis_type", "status", "started_by", "estimated_cost", "created_at"]
    list_filter = ["status", "analysis_type", "team", "created_at"]
    search_fields = ["image__name", "started_by__email", "celery_task_id"]
    readonly_fields = ["id", "celery_task_id", "duration", "created_at", "updated_at"]

    fieldsets = (
        (None, {"fields": ("image", "analysis_type", "status", "started_by", "team")}),
        (
            "Processing",
            {
                "fields": ("celery_task_id", "progress_percentage", "started_at", "completed_at", "error_message"),
            },
        ),
        (
            "Credits",
            {
                "fields": ("estimated_cost", "actual_cost"),
            },
        ),
        ("Metadata", {"fields": ("id", "created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(AnalysisResult)
class AnalysisResultAdmin(admin.ModelAdmin):
    list_display = ["job", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["job__image__name", "job__started_by__email"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ["user", "transaction_type", "amount", "description", "team", "created_at"]
    list_filter = ["transaction_type", "team", "created_at"]
    search_fields = ["user__email", "description", "stripe_charge_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
