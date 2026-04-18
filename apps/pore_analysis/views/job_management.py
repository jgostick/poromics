from django.shortcuts import get_object_or_404, render

from apps.pore_analysis.models import AnalysisJob
from apps.teams.decorators import login_and_team_required

from .utils import get_pore_analysis_context


@login_and_team_required
def job_list(request, team_slug):
    jobs = AnalysisJob.objects.filter(team=request.team).order_by("-created_at")
    context = {
        "jobs": jobs,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
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
