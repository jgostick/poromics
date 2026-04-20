import datetime

from django.conf import settings
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.users.models import CustomUser


def get_user_signups(start: datetime.date | None = None, end: datetime.date | None = None, include_unconfirmed=None):
    extra_filter_kwargs = {}
    if include_unconfirmed is None:
        include_unconfirmed = settings.ACCOUNT_EMAIL_VERIFICATION != "mandatory"
    if not include_unconfirmed:
        extra_filter_kwargs = {
            "emailaddress__verified": True,
        }
    end = end or timezone.now()
    start = start or end - datetime.timedelta(days=90)
    data = (
        CustomUser.objects.filter(date_joined__gte=start, date_joined__lte=end, **extra_filter_kwargs)
        .annotate(date=TruncDate("date_joined"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )
    return [{"date": item["date"], "count": item["count"]} for item in data]


# ---------------------------------------------------------------------------
# Site-admin service functions
# ---------------------------------------------------------------------------

def get_global_job_stats():
    """Return aggregate job counts by status across all teams."""
    from apps.pore_analysis.models import AnalysisJob, JobStatus

    return AnalysisJob.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=JobStatus.PENDING)),
        processing=Count("id", filter=Q(status=JobStatus.PROCESSING)),
        completed=Count("id", filter=Q(status=JobStatus.COMPLETED)),
        failed=Count("id", filter=Q(status=JobStatus.FAILED)),
        cancelled=Count("id", filter=Q(status=JobStatus.CANCELLED)),
    )


def get_global_jobs(status=None, analysis_type=None, team_id=None, start=None, end=None):
    """Return a filtered queryset of AnalysisJobs across all teams."""
    from apps.pore_analysis.models import AnalysisJob

    qs = AnalysisJob.objects.select_related("team", "image", "started_by").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if analysis_type:
        qs = qs.filter(analysis_type=analysis_type)
    if team_id:
        qs = qs.filter(team_id=team_id)
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return qs


def get_credits_by_team():
    """Return all teams annotated with credit balance, total purchased, and total used."""
    from apps.teams.models import Team

    return Team.objects.annotate(
        balance=Sum("credittransaction__amount"),
        total_purchased=Sum(
            "credittransaction__amount",
            filter=Q(credittransaction__transaction_type="purchase"),
        ),
        total_used=Sum(
            "credittransaction__amount",
            filter=Q(credittransaction__transaction_type="usage"),
        ),
    ).order_by("name")


def get_users_with_teams():
    """Return all users with their team memberships prefetched, ordered by last login."""
    from apps.teams.models import Membership

    return (
        CustomUser.objects.prefetch_related(
            Prefetch("membership_set", queryset=Membership.objects.select_related("team"))
        )
        .annotate(team_count=Count("teams"))
        .order_by("-last_login")
    )


def get_celery_status():
    """Inspect Celery broker and workers; return a status dict safe to display."""
    from kombu.exceptions import OperationalError

    from apps.pore_analysis.tasks import run_permeability_job

    app = run_permeability_job.app
    result = {
        "broker_ok": False,
        "broker_error": None,
        "workers_detail": [],
        "any_active_tasks": False,
        "any_reserved_tasks": False,
        "inspect_error": None,
    }

    try:
        with app.connection_for_read() as conn:
            conn.ensure_connection(max_retries=1)
        result["broker_ok"] = True
    except OperationalError as exc:
        result["broker_error"] = str(exc)
        return result

    try:
        insp = app.control.inspect(timeout=2.0)
        pings = insp.ping() or {}
        active_queues = insp.active_queues() or {}
        active_tasks = insp.active() or {}
        reserved_tasks = insp.reserved() or {}

        workers_detail = []
        for worker in pings:
            workers_detail.append({
                "name": worker,
                "status": "ok",
                "queues": [q["name"] for q in active_queues.get(worker, [])],
                "active": [
                    {"name": t.get("name", ""), "id": t.get("id", "")}
                    for t in active_tasks.get(worker, [])
                ],
                "reserved": [
                    {"name": t.get("name", ""), "id": t.get("id", "")}
                    for t in reserved_tasks.get(worker, [])
                ],
            })
        result["workers_detail"] = workers_detail
        result["any_active_tasks"] = any(w["active"] for w in workers_detail)
        result["any_reserved_tasks"] = any(w["reserved"] for w in workers_detail)
    except Exception as exc:
        result["inspect_error"] = str(exc)

    return result
