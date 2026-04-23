from django.db.models import Sum
from django.shortcuts import render
from kombu.exceptions import OperationalError

from apps.pore_analysis.models import AnalysisJob, AnalysisType, CreditTransaction, UploadedImage
from apps.pore_analysis.queue_catalog import get_enabled_queues
from apps.pore_analysis.tasks import run_permeability_job  # add to imports at top of file
from apps.teams.decorators import login_and_team_required


def _build_analysis_backend_queue_map(analysis_type: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for queue in get_enabled_queues(analysis_type=analysis_type):
        backend = str(queue.get("backend_key") or "default")
        mapping.setdefault(backend, queue["name"])
    return mapping


TAICHI_QUEUE_MAP = _build_analysis_backend_queue_map(AnalysisType.PERMEABILITY)
JULIA_QUEUE_MAP = _build_analysis_backend_queue_map(AnalysisType.DIFFUSIVITY)
BASIC_CPU_QUEUE_MAP = _build_analysis_backend_queue_map(AnalysisType.PORESIZE)
NETWORK_EXTRACTION_QUEUE_MAP = _build_analysis_backend_queue_map(AnalysisType.NETWORK_EXTRACTION)
NETWORK_VALIDATION_QUEUE_MAP = _build_analysis_backend_queue_map(AnalysisType.NETWORK_VALIDATION)

# Compatibility aliases for older jobs that saved backend="cpu" for default-only queues.
if "default" in BASIC_CPU_QUEUE_MAP:
    BASIC_CPU_QUEUE_MAP.setdefault("cpu", BASIC_CPU_QUEUE_MAP["default"])
if "default" in NETWORK_VALIDATION_QUEUE_MAP:
    NETWORK_VALIDATION_QUEUE_MAP.setdefault("cpu", NETWORK_VALIDATION_QUEUE_MAP["default"])


def _celery_queue_ready(queue_name: str, timeout: float = 1.5) -> tuple[bool, str]:
    """
    Returns (is_ready, reason).
    Ready means broker is reachable and at least one worker consumes queue_name.
    """
    app = run_permeability_job.app

    # 1) Broker connection check
    try:
        with app.connection_for_read() as conn:
            conn.ensure_connection(max_retries=1)
    except OperationalError as exc:
        return False, f"Broker unreachable: {exc}"

    # 2) Worker liveness + queue subscription check
    try:
        insp = app.control.inspect(timeout=timeout)
        pings = insp.ping() or {}
        if not pings:
            return False, "No Celery workers responded to ping."

        active_queues = insp.active_queues() or {}
        for worker, queues in active_queues.items():
            for q in queues:
                if q.get("name") == queue_name:
                    return True, f"Worker {worker} ready on {queue_name}"

        return False, f"No worker is consuming queue '{queue_name}'."
    except Exception as exc:
        return False, f"Celery inspect failed: {exc}"


def _broker_ready(app) -> tuple[bool, str]:
    try:
        with app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1)
        return True, "ok"
    except OperationalError as exc:
        return False, f"Broker unreachable: {exc}"


def get_pore_analysis_context(request):
    """Get common context data for pore analysis templates."""
    if not hasattr(request, "team"):
        return {}

    context = {
        "team_slug": request.team.slug,
        "image_count": UploadedImage.objects.filter(team=request.team).count(),
        "job_count": AnalysisJob.objects.filter(team=request.team).exclude(status="completed").count(),
    }

    # Calculate credit balance
    credit_balance = (
        CreditTransaction.objects.filter(team=request.team).aggregate(balance=Sum("amount"))["balance"] or 0
    )
    context["credit_balance"] = credit_balance

    return context


@login_and_team_required
def dashboard(request, team_slug):
    """Main dashboard showing recent uploads, jobs, and credit balance."""
    team = request.team

    # Get recent data for the team
    recent_images = UploadedImage.objects.filter(team=team).order_by("-created_at")[:5]
    recent_jobs = AnalysisJob.objects.filter(team=team).order_by("-created_at")[:5]

    context = {
        "recent_images": recent_images,
        "recent_jobs": recent_jobs,
        "analysis_types": AnalysisType.choices,
    }

    # Add sidebar context
    context.update(get_pore_analysis_context(request))

    return render(request, "pore_analysis/dashboard.html", context)
