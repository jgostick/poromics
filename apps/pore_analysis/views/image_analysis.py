from decimal import Decimal

from django.contrib import messages
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from kombu.exceptions import OperationalError

from apps.pore_analysis.forms import DiffusivityLaunchForm, PermeabilityLaunchForm
from apps.pore_analysis.models import AnalysisJob, AnalysisType, JobStatus, UploadedImage
from apps.pore_analysis.tasks import run_diffusivity_job, run_permeability_job
from apps.teams.decorators import login_and_team_required

from .utils import JULIA_QUEUE_MAP, get_pore_analysis_context

BACKEND_QUEUE_MAP = {  # add near top of file, outside the view function
    'cpu': 'kabs-cpu',
    'gpu': 'kabs-gpu',
    'metal': 'kabs-metal',
    'cuda': 'kabs-cuda',
    'opengl': 'kabs-opengl',
}


@login_and_team_required
def start_analysis(request, team_slug, image_id):
    """Start a new analysis on an uploaded image."""
    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    
    if request.method == 'POST':
        analysis_type = request.POST.get('analysis_type')
        if analysis_type in dict(AnalysisType.choices):
            # TODO: Create analysis job and start Celery task
            messages.success(request, _('Analysis started!'))
            return redirect('pore_analysis:image_detail', team_slug=team_slug, image_id=image_id)
        else:
            messages.error(request, _('Invalid analysis type selected.'))
    
    return redirect('pore_analysis:image_detail', team_slug=team_slug, image_id=image_id)


def _broker_ready(app) -> tuple[bool, str]:
    try:
        with app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1)
        return True, "ok"
    except OperationalError as exc:
        return False, f"Broker unreachable: {exc}"


@login_and_team_required
def permeability_launch(request, team_slug):
    if request.method == "POST":
        form = PermeabilityLaunchForm(request.team, request.POST)
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()
            queue = BACKEND_QUEUE_MAP.get(params["backend"], "kabs-cpu")

            ok, reason = _broker_ready(run_permeability_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:permeability_launch", team_slug=team_slug)

            job = AnalysisJob.objects.create(
                team=request.team,
                image=image,
                analysis_type=AnalysisType.PERMEABILITY,
                started_by=request.user,
                estimated_cost=Decimal("0.00"),
                parameters=params,
                status=JobStatus.PENDING,
            )

            try:
                task = run_permeability_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error_message = f"Failed to enqueue task: {exc}"
                job.completed_at = timezone.now()
                job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s'. %(reason)s") % {
                        "queue": queue,
                        "reason": str(exc),
                    },
                )
                return redirect("pore_analysis_team:permeability_launch", team_slug=team_slug)

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            messages.success(request, _("Permeability job queued."))
            return redirect("pore_analysis_team:job_detail", team_slug=team_slug, job_id=job.id)
    else:
        form = PermeabilityLaunchForm(request.team)

    context = {
        "form": form,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/permeability_launch.html", context)


@login_and_team_required
def diffusivity_launch(request, team_slug):
    if request.method == "POST":
        form = DiffusivityLaunchForm(request.team, request.POST)
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()
            queue = JULIA_QUEUE_MAP.get(params["backend"], "julia-cpu")

            ok, reason = _broker_ready(run_diffusivity_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:diffusivity_launch", team_slug=team_slug)

            job = AnalysisJob.objects.create(
                team=request.team,
                image=image,
                analysis_type=AnalysisType.DIFFUSIVITY,
                started_by=request.user,
                estimated_cost=Decimal("0.00"),
                parameters=params,
                status=JobStatus.PENDING,
            )

            try:
                task = run_diffusivity_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error_message = f"Failed to enqueue task: {exc}"
                job.completed_at = timezone.now()
                job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s'. %(reason)s") % {
                        "queue": queue,
                        "reason": str(exc),
                    },
                )
                return redirect("pore_analysis_team:diffusivity_launch", team_slug=team_slug)

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            messages.success(request, _("Diffusivity job queued."))
            return redirect("pore_analysis_team:job_detail", team_slug=team_slug, job_id=job.id)
    else:
        form = DiffusivityLaunchForm(request.team)

    context = {
        "form": form,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/diffusivity_launch.html", context)