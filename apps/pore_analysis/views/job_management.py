from django.shortcuts import get_object_or_404, render

from apps.pore_analysis.models import AnalysisJob, AnalysisType
from apps.teams.decorators import login_and_team_required

from .utils import BACKEND_QUEUE_MAP, JULIA_QUEUE_MAP, get_pore_analysis_context


@login_and_team_required
def job_list(request, team_slug):
    jobs = list(AnalysisJob.objects.filter(team=request.team).order_by("-created_at"))

    # Derive backend and queue from existing JSON parameters (no schema change).
    for job in jobs:
        backend = (job.parameters or {}).get("backend")
        job.backend_name = backend or "-"

        queue_map = BACKEND_QUEUE_MAP
        if job.analysis_type == AnalysisType.DIFFUSIVITY:
            queue_map = JULIA_QUEUE_MAP

        job.queue_name = queue_map.get(backend, "-")

    context = {
        "jobs": jobs,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))

    if request.htmx:
        return render(request, "pore_analysis/components/job_table.html", context)

    return render(request, "pore_analysis/job_list.html", context)


@login_and_team_required
def job_detail(request, team_slug, job_id):
    job = get_object_or_404(AnalysisJob, id=job_id, team=request.team)
    context = {
        "job": job,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/job_detail.html", context)
