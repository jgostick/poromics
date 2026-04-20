from datetime import date, datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.dashboard.forms import AdminJobFilterForm, DateRangeForm
from apps.dashboard.services import (
    get_celery_status,
    get_credits_by_team,
    get_global_job_stats,
    get_global_jobs,
    get_user_signups,
    get_users_with_teams,
)
from apps.users.models import CustomUser


def _string_to_date(date_str: str) -> date:
    date_format = "%Y-%m-%d"
    return datetime.strptime(date_str, date_format).date()


def _superuser_required(view_func):
    """Combines superuser check and staff_member_required."""
    return user_passes_test(lambda u: u.is_superuser, login_url="/404")(staff_member_required(view_func))


@_superuser_required
def dashboard(request):
    end_str = request.GET.get("end")
    end = _string_to_date(end_str) if end_str else timezone.now().date() + timedelta(days=1)
    start_str = request.GET.get("start")
    start = _string_to_date(start_str) if start_str else end - timedelta(days=90)
    form = DateRangeForm(initial={"start": start, "end": end})
    start_value = CustomUser.objects.filter(date_joined__lt=start).count()
    return TemplateResponse(
        request,
        "dashboard/user_dashboard.html",
        context={
            "active_tab": "project-dashboard",
            "signup_data": get_user_signups(start, end),
            "form": form,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "start_value": start_value,
        },
    )


@_superuser_required
def admin_jobs(request):
    form = AdminJobFilterForm(request.GET or None)
    filters = {}
    if form.is_valid():
        filters["status"] = form.cleaned_data.get("status") or None
        filters["analysis_type"] = form.cleaned_data.get("analysis_type") or None
        filters["team_id"] = form.cleaned_data.get("team") or None
        filters["start"] = form.cleaned_data.get("start")
        filters["end"] = form.cleaned_data.get("end")
    else:
        form = AdminJobFilterForm()

    jobs_qs = get_global_jobs(**filters)
    stats = get_global_job_stats()
    paginator = Paginator(jobs_qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    return TemplateResponse(
        request,
        "dashboard/site_admin/jobs.html",
        context={
            "active_tab": "admin-jobs",
            "form": form,
            "page_obj": page,
            "stats": stats,
        },
    )


@_superuser_required
def admin_users(request):
    users_qs = get_users_with_teams()
    paginator = Paginator(users_qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    return TemplateResponse(
        request,
        "dashboard/site_admin/users.html",
        context={
            "active_tab": "admin-users",
            "page_obj": page,
        },
    )


@_superuser_required
def admin_credits(request):
    teams = get_credits_by_team()
    return TemplateResponse(
        request,
        "dashboard/site_admin/credits.html",
        context={
            "active_tab": "admin-credits",
            "teams": teams,
        },
    )


@_superuser_required
def admin_celery(request):
    status = get_celery_status()
    return TemplateResponse(
        request,
        "dashboard/site_admin/celery.html",
        context={
            "active_tab": "admin-celery",
            "celery": status,
        },
    )
