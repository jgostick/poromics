from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, render

from apps.pore_analysis.models import AnalysisJob, AnalysisType, JobStatus, UploadedImage
from apps.teams.decorators import login_and_team_required

from .utils import (
    BASIC_CPU_QUEUE_MAP,
    JULIA_QUEUE_MAP,
    NETWORK_EXTRACTION_QUEUE_MAP,
    TAICHI_QUEUE_MAP,
    get_pore_analysis_context,
)


@login_and_team_required
def job_list(request, team_slug):
    image_id = (request.GET.get("image_id") or "").strip()
    status = (request.GET.get("status") or "").strip()
    analysis_type = (request.GET.get("analysis_type") or "").strip()
    sort_by = (request.GET.get("sort_by") or "created").strip()
    sort_dir = (request.GET.get("sort_dir") or "desc").strip().lower()

    sort_fields = {
        "type": "analysis_type",
        "image": "image__name",
        "status": "status",
        "progress": "progress_percentage",
        "created": "created_at",
    }

    if sort_by not in sort_fields:
        sort_by = "created"

    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"

    order_field = sort_fields[sort_by]
    if sort_dir == "desc":
        order_field = f"-{order_field}"

    jobs_qs = AnalysisJob.objects.filter(team=request.team)

    if image_id:
        jobs_qs = jobs_qs.filter(image_id=image_id)

    if status and status in JobStatus.values:
        jobs_qs = jobs_qs.filter(status=status)

    if analysis_type and analysis_type in AnalysisType.values:
        jobs_qs = jobs_qs.filter(analysis_type=analysis_type)

    jobs = list(jobs_qs.order_by(order_field))

    # Derive backend and queue from existing JSON parameters (no schema change).
    for job in jobs:
        backend = (job.parameters or {}).get("backend")
        job.backend_name = backend or "-"

        queue_map = TAICHI_QUEUE_MAP
        if job.analysis_type == AnalysisType.DIFFUSIVITY:
            queue_map = JULIA_QUEUE_MAP
        elif job.analysis_type == AnalysisType.NETWORK_EXTRACTION:
            queue_map = NETWORK_EXTRACTION_QUEUE_MAP
        elif job.analysis_type not in {AnalysisType.PERMEABILITY}:
            queue_map = BASIC_CPU_QUEUE_MAP

        job.queue_name = queue_map.get(backend, "-")

    base_query_params = {
        key: value
        for key, value in {
            "image_id": image_id,
            "status": status,
            "analysis_type": analysis_type,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        }.items()
        if value
    }

    sort_querystrings = {}
    for column_key in sort_fields:
        next_dir = "asc"
        if sort_by == column_key and sort_dir == "asc":
            next_dir = "desc"

        query = {
            key: value
            for key, value in {
                "image_id": image_id,
                "status": status,
                "analysis_type": analysis_type,
                "sort_by": column_key,
                "sort_dir": next_dir,
            }.items()
            if value
        }
        sort_querystrings[column_key] = urlencode(query)

    context = {
        "jobs": jobs,
        "team_slug": team_slug,
        "images": UploadedImage.objects.filter(team=request.team).order_by("name"),
        "image_id": image_id,
        "selected_status": status,
        "selected_analysis_type": analysis_type,
        "selected_sort_by": sort_by,
        "selected_sort_dir": sort_dir,
        "status_choices": JobStatus.choices,
        "analysis_type_choices": AnalysisType.choices,
        "sort_querystrings": sort_querystrings,
        "filters_querystring": urlencode(base_query_params),
    }
    context.update(get_pore_analysis_context(request))

    if request.GET.get("partial") == "1":
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
