from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from kombu.exceptions import OperationalError

from apps.pore_analysis.analysis.pricing import (
    InsufficientCreditsError,
    NoPricingRateError,
    calculate_estimated_credits,
    charge_job_upfront,
    ensure_sufficient_credits,
    get_team_credit_balance,
    refund_job_charge,
)
from apps.pore_analysis.forms import (
    DiffusivityLaunchForm,
    NetworkExtractionLaunchForm,
    NetworkValidationLaunchForm,
    PermeabilityLaunchForm,
    PoreSizeLaunchForm,
)
from apps.pore_analysis.models import AnalysisJob, AnalysisType, JobStatus, UploadedImage
from apps.pore_analysis.tasks import (
    run_diffusivity_job,
    run_network_extraction_job,
    run_network_validation_job,
    run_permeability_job,
    run_poresize_job,
)
from apps.teams.decorators import login_and_team_required

from .utils import (
    get_pore_analysis_context,
)


@login_and_team_required
def start_analysis(request, team_slug, image_id):
    """Start a new analysis on an uploaded image."""
    get_object_or_404(UploadedImage, id=image_id, team=request.team)

    if request.method == "POST":
        analysis_type = request.POST.get("analysis_type")
        if analysis_type in dict(AnalysisType.choices):
            # TODO: Create analysis job and start Celery task
            messages.success(request, _("Analysis started!"))
            return redirect("pore_analysis:image_detail", team_slug=team_slug, image_id=image_id)
        else:
            messages.error(request, _("Invalid analysis type selected."))

    return redirect("pore_analysis:image_detail", team_slug=team_slug, image_id=image_id)


def _broker_ready(app) -> tuple[bool, str]:
    try:
        with app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1)
        return True, "ok"
    except OperationalError as exc:
        return False, f"Broker unreachable: {exc}"


def _create_job_with_upfront_charge(*, team, user, image, analysis_type: str, parameters: dict) -> AnalysisJob:
    estimated_credits = calculate_estimated_credits(
        image=image,
        analysis_type=analysis_type,
        parameters=parameters,
    )
    ensure_sufficient_credits(team=team, required_credits=estimated_credits)

    with transaction.atomic():
        job = AnalysisJob.objects.create(
            team=team,
            image=image,
            analysis_type=analysis_type,
            started_by=user,
            estimated_cost=estimated_credits,
            parameters=parameters,
            status=JobStatus.PENDING,
        )
        charge_job_upfront(job)

    return job


def _with_routing_metadata(parameters: dict, *, queue: str, endpoint_url: str | None = None) -> dict:
    enriched = dict(parameters)
    enriched["queue_name"] = queue
    if endpoint_url:
        enriched["endpoint_url"] = endpoint_url
    return enriched


def _mark_enqueue_failure_with_refund(job: AnalysisJob, exc: Exception) -> None:
    with transaction.atomic():
        refund_job_charge(job, reason="failed to enqueue")
        job.status = JobStatus.FAILED
        job.actual_cost = Decimal("0.00")
        job.error_message = f"Failed to enqueue task: {exc}"
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "actual_cost", "error_message", "completed_at", "updated_at"])


def _handle_pricing_errors(request, exc: Exception, redirect_name: str, team_slug: str):
    if isinstance(exc, NoPricingRateError):
        messages.error(
            request,
            _("Pricing is not configured for this analysis queue. %(reason)s") % {"reason": str(exc)},
        )
    elif isinstance(exc, InsufficientCreditsError):
        messages.error(
            request,
            _("Not enough credits to start this job. %(reason)s") % {"reason": str(exc)},
        )
    return redirect(redirect_name, team_slug=team_slug)


@login_and_team_required
def estimate_job_cost(request, team_slug):
    analysis_type = (request.GET.get("analysis_type") or "").strip()
    image_id = (request.GET.get("image") or "").strip()
    queue_name = (request.GET.get("queue_name") or "").strip()
    backend = (request.GET.get("backend") or "default").strip()

    if analysis_type not in dict(AnalysisType.choices):
        return JsonResponse({"ok": False, "error": "Invalid analysis type."}, status=400)

    if not image_id:
        return JsonResponse({"ok": False, "error": "Select an image to estimate cost."}, status=400)

    try:
        image = UploadedImage.objects.get(id=image_id, team=request.team)
    except UploadedImage.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Image not found."}, status=404)

    try:
        estimated_credits = calculate_estimated_credits(
            image=image,
            analysis_type=analysis_type,
            parameters={
                "queue_name": queue_name,
                "backend": backend,
            },
        )
        balance = get_team_credit_balance(request.team)
    except NoPricingRateError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "estimated_credits": f"{estimated_credits:.2f}",
            "balance": f"{balance:.2f}",
            "can_afford": balance >= estimated_credits,
        }
    )


@login_and_team_required
def permeability_launch(request, team_slug):
    if request.method == "POST":
        form = PermeabilityLaunchForm(request.team, request.POST)
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()
            queue = params["queue_name"]
            endpoint = settings.TAICHI_QUEUE_ENDPOINTS.get(queue, settings.TAICHI_DEFAULT_SERVER_URL).strip()
            job_params = _with_routing_metadata(params, queue=queue, endpoint_url=endpoint or None)

            ok, reason = _broker_ready(run_permeability_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:permeability_launch", team_slug=team_slug)

            if endpoint:
                from taichi_client import _server_healthy as _taichi_server_healthy

                if not _taichi_server_healthy(endpoint):
                    messages.error(
                        request,
                        _("Taichi service for queue '%(queue)s' is unreachable at %(endpoint)s.")
                        % {"queue": queue, "endpoint": endpoint},
                    )
                    return redirect("pore_analysis_team:permeability_launch", team_slug=team_slug)

            try:
                job = _create_job_with_upfront_charge(
                    team=request.team,
                    user=request.user,
                    image=image,
                    analysis_type=AnalysisType.PERMEABILITY,
                    parameters=job_params,
                )
            except (NoPricingRateError, InsufficientCreditsError) as exc:
                return _handle_pricing_errors(
                    request,
                    exc,
                    "pore_analysis_team:permeability_launch",
                    team_slug,
                )

            try:
                task = run_permeability_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                _mark_enqueue_failure_with_refund(job, exc)
                error_template = _("Could not queue job on '%(queue)s'. %(reason)s")
                if endpoint:
                    error_template = _("Could not queue job on '%(queue)s' (endpoint %(endpoint)s). %(reason)s")
                messages.error(
                    request,
                    error_template
                    % {
                        "queue": queue,
                        "endpoint": endpoint,
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
            queue = params["queue_name"]
            endpoint = settings.JULIA_QUEUE_ENDPOINTS.get(queue, settings.JULIA_DEFAULT_SERVER_URL)
            job_params = _with_routing_metadata(params, queue=queue, endpoint_url=endpoint)

            ok, reason = _broker_ready(run_diffusivity_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:diffusivity_launch", team_slug=team_slug)

            from julia_client import _server_healthy

            if not _server_healthy(endpoint):
                messages.error(
                    request,
                    _("Julia service for queue '%(queue)s' is unreachable at %(endpoint)s.")
                    % {"queue": queue, "endpoint": endpoint},
                )
                return redirect("pore_analysis_team:diffusivity_launch", team_slug=team_slug)

            try:
                job = _create_job_with_upfront_charge(
                    team=request.team,
                    user=request.user,
                    image=image,
                    analysis_type=AnalysisType.DIFFUSIVITY,
                    parameters=job_params,
                )
            except (NoPricingRateError, InsufficientCreditsError) as exc:
                return _handle_pricing_errors(
                    request,
                    exc,
                    "pore_analysis_team:diffusivity_launch",
                    team_slug,
                )

            try:
                task = run_diffusivity_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                _mark_enqueue_failure_with_refund(job, exc)
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s' (endpoint %(endpoint)s). %(reason)s")
                    % {
                        "queue": queue,
                        "endpoint": endpoint,
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


@login_and_team_required
def pore_size_launch(request, team_slug):

    FORM_CLASS = PoreSizeLaunchForm
    ANALYSIS_TYPE_ENUM = AnalysisType.PORESIZE
    TASK_FUNCTION = run_poresize_job
    TEMPLATE_PATH = "pore_analysis/poresize_launch.html"
    SUCCESS_MESSAGE = _("Pore size job queued.")
    REDIRECT_NAME_ON_ERROR = "pore_analysis_team:poresize_launch"

    # 1) Build/bind the form
    if request.method == "POST":
        form = FORM_CLASS(request.team, request.POST)

        # 2) Validate user input
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()

            # 3) Pick queue directly from the submitted form.
            queue = params["queue_name"]
            job_params = _with_routing_metadata(params, queue=queue)

            # 4) Ensure broker connectivity before creating enqueue side effects
            ok, reason = _broker_ready(TASK_FUNCTION.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect(REDIRECT_NAME_ON_ERROR, team_slug=team_slug)

            # 5) Create AnalysisJob row and charge credits up front
            try:
                job = _create_job_with_upfront_charge(
                    team=request.team,
                    user=request.user,
                    image=image,
                    analysis_type=ANALYSIS_TYPE_ENUM,
                    parameters=job_params,
                )
            except (NoPricingRateError, InsufficientCreditsError) as exc:
                return _handle_pricing_errors(request, exc, REDIRECT_NAME_ON_ERROR, team_slug)

            # 6) Enqueue celery task (capture and handle enqueue failure)
            try:
                task = TASK_FUNCTION.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                _mark_enqueue_failure_with_refund(job, exc)
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s'. %(reason)s")
                    % {
                        "queue": queue,
                        "reason": str(exc),
                    },
                )
                return redirect(REDIRECT_NAME_ON_ERROR, team_slug=team_slug)

            # 7) Store celery task id for tracking
            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id", "updated_at"])

            # 8) Redirect to job detail
            messages.success(request, SUCCESS_MESSAGE)
            return redirect("pore_analysis_team:job_detail", team_slug=team_slug, job_id=job.id)

    else:
        form = FORM_CLASS(request.team)

    # Standard context pattern used by other launch pages
    context = {
        "form": form,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, TEMPLATE_PATH, context)


@login_and_team_required
def network_extraction_launch(request, team_slug):
    if request.method == "POST":
        form = NetworkExtractionLaunchForm(request.team, request.POST)
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()
            queue = params["queue_name"]
            job_params = _with_routing_metadata(params, queue=queue)

            ok, reason = _broker_ready(run_network_extraction_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:network_extraction_launch", team_slug=team_slug)

            try:
                job = _create_job_with_upfront_charge(
                    team=request.team,
                    user=request.user,
                    image=image,
                    analysis_type=AnalysisType.NETWORK_EXTRACTION,
                    parameters=job_params,
                )
            except (NoPricingRateError, InsufficientCreditsError) as exc:
                return _handle_pricing_errors(
                    request,
                    exc,
                    "pore_analysis_team:network_extraction_launch",
                    team_slug,
                )

            try:
                task = run_network_extraction_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                _mark_enqueue_failure_with_refund(job, exc)
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s'. %(reason)s")
                    % {
                        "queue": queue,
                        "reason": str(exc),
                    },
                )
                return redirect("pore_analysis_team:network_extraction_launch", team_slug=team_slug)

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            messages.success(request, _("Network extraction job queued."))
            return redirect("pore_analysis_team:job_detail", team_slug=team_slug, job_id=job.id)
    else:
        form = NetworkExtractionLaunchForm(request.team)

    context = {
        "form": form,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/network_extraction_launch.html", context)


@login_and_team_required
def network_validation_launch(request, team_slug):
    if request.method == "POST":
        form = NetworkValidationLaunchForm(request.team, request.POST)
        if form.is_valid():
            image = form.cleaned_data["image"]
            params = form.to_parameters()
            queue = params["queue_name"]
            job_params = _with_routing_metadata(params, queue=queue)

            ok, reason = _broker_ready(run_network_validation_job.app)
            if not ok:
                messages.error(request, _("Queue service unavailable. %(reason)s") % {"reason": reason})
                return redirect("pore_analysis_team:network_validation_launch", team_slug=team_slug)

            try:
                job = _create_job_with_upfront_charge(
                    team=request.team,
                    user=request.user,
                    image=image,
                    analysis_type=AnalysisType.NETWORK_VALIDATION,
                    parameters=job_params,
                )
            except (NoPricingRateError, InsufficientCreditsError) as exc:
                return _handle_pricing_errors(
                    request,
                    exc,
                    "pore_analysis_team:network_validation_launch",
                    team_slug,
                )

            try:
                task = run_network_validation_job.apply_async(args=[str(job.id)], queue=queue)
            except Exception as exc:
                _mark_enqueue_failure_with_refund(job, exc)
                messages.error(
                    request,
                    _("Could not queue job on '%(queue)s'. %(reason)s")
                    % {
                        "queue": queue,
                        "reason": str(exc),
                    },
                )
                return redirect("pore_analysis_team:network_validation_launch", team_slug=team_slug)

            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id", "updated_at"])
            messages.success(request, _("Network validation job queued."))
            return redirect("pore_analysis_team:job_detail", team_slug=team_slug, job_id=job.id)
    else:
        form = NetworkValidationLaunchForm(request.team)

    context = {
        "form": form,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/network_validation_launch.html", context)


@login_and_team_required
def network_jobs_for_image(request, team_slug):
    """HTMX endpoint: return <option> elements for completed network extraction jobs for a given image."""
    from apps.pore_analysis.models import AnalysisJob, AnalysisType, JobStatus

    image_id = (request.GET.get("image") or "").strip()
    jobs = AnalysisJob.objects.none()
    if image_id:
        jobs = (
            AnalysisJob.objects.filter(
                team=request.team,
                image_id=image_id,
                analysis_type=AnalysisType.NETWORK_EXTRACTION,
                status=JobStatus.COMPLETED,
                result__network_file__isnull=False,
            )
            .exclude(
                result__network_file="",
            )
            .order_by("-created_at")
        )

    return render(request, "pore_analysis/components/network_job_options.html", {"jobs": jobs})
