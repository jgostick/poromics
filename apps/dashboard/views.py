from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.dashboard.forms import (
    AdminCreditGrantForm,
    AdminJobFilterForm,
    AdminRunPodCreateForm,
    AdminRunPodQueueMappingForm,
    DateRangeForm,
)
from apps.dashboard.services import (
    get_celery_status,
    get_credits_by_team,
    get_global_job_stats,
    get_global_jobs,
    get_user_signups,
    get_users_with_teams,
)
from apps.pore_analysis.models import CreditTransaction, RunPodQueueMapping
from apps.pore_analysis.queue_catalog import get_queue_endpoint, get_runpod_queue_choices
from apps.users.models import CustomUser
from apps.utils import runpod_pods


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
    if request.method == "POST":
        form = AdminCreditGrantForm(request.POST)
        if form.is_valid():
            team_id = form.cleaned_data["team"]
            credit_user = form.cleaned_data.get("user") or request.user
            CreditTransaction.objects.create(
                team_id=team_id,
                user=credit_user,
                transaction_type="purchase",
                amount=form.cleaned_data["amount"],
                description=form.cleaned_data["description"],
            )
            messages.success(request, "Credits added successfully.")
            return redirect("dashboard:admin_credits")
        messages.error(request, "Please correct the credit form errors below.")
    else:
        form = AdminCreditGrantForm()

    teams = get_credits_by_team()
    return TemplateResponse(
        request,
        "dashboard/site_admin/credits.html",
        context={
            "active_tab": "admin-credits",
            "form": form,
            "teams": teams,
        },
    )


@_superuser_required
def admin_celery(request):
    return TemplateResponse(
        request,
        "dashboard/site_admin/celery.html",
        context={
            "active_tab": "admin-celery",
        },
    )


@_superuser_required
def admin_pods(request):
    creation_options = runpod_pods.get_creation_options()

    if request.method == "POST":
        form = AdminRunPodCreateForm(request.POST, creation_options=creation_options)
        if form.is_valid():
            spec = {
                "pod_name": form.cleaned_data["pod_name"],
                "image_name": form.cleaned_data["image_name"],
                "compute_type": form.cleaned_data["compute_type"],
                "gpu_type_id": form.cleaned_data.get("gpu_type_id") or "",
                "cpu_flavor_id": form.cleaned_data.get("cpu_flavor_id") or "",
                "data_center_id": form.cleaned_data.get("data_center_id") or "",
                "cloud_type": form.cleaned_data.get("cloud_type") or "",
                "interruptible": form.cleaned_data.get("interruptible", False),
                "ports": form.cleaned_data.get("parsed_ports") or form.cleaned_data.get("ports") or "",
                "env": form.cleaned_data.get("parsed_env") or {},
            }

            try:
                pod = runpod_pods.create_pod(spec)
            except runpod_pods.RunPodError as exc:
                messages.error(request, f"Unable to create pod: {exc}")
            else:
                pod_name = pod.get("name") or pod.get("id") or "pod"
                messages.success(request, f"RunPod pod '{pod_name}' is ready.")
                return redirect("dashboard:admin_pods")
        else:
            messages.error(request, "Please correct the pod form errors below.")
    else:
        form = AdminRunPodCreateForm(creation_options=creation_options)

    try:
        pods = runpod_pods.list_pods()
    except runpod_pods.RunPodError as exc:
        messages.error(request, f"Unable to load pods: {exc}")
        pods = []

    mappings = list(RunPodQueueMapping.objects.order_by("queue_name"))
    mapping_by_pod_id = {mapping.pod_id: mapping for mapping in mappings}
    queue_to_pod = {mapping.queue_name: mapping.pod_id for mapping in mappings}

    queue_choices = get_runpod_queue_choices()
    pods_with_mappings = []
    for pod in pods:
        pod_id = str(pod.get("id") or "").strip()
        pod_specific_queue_choices = []
        for queue_name, label in queue_choices:
            mapped_pod_id = queue_to_pod.get(queue_name)
            if mapped_pod_id and mapped_pod_id != pod_id:
                continue
            pod_specific_queue_choices.append((queue_name, label))

        pod_row = dict(pod)
        pod_row["mapping"] = mapping_by_pod_id.get(pod_id)
        pod_row["queue_choices"] = pod_specific_queue_choices
        pods_with_mappings.append(pod_row)

    return TemplateResponse(
        request,
        "dashboard/site_admin/pods.html",
        context={
            "active_tab": "admin-pods",
            "form": form,
            "pods": pods_with_mappings,
            "options_source": creation_options.get("source"),
            "options_warning": creation_options.get("warning"),
        },
    )


@_superuser_required
def admin_pod_map(request, pod_id: str):
    if request.method != "POST":
        return redirect("dashboard:admin_pods")

    form = AdminRunPodQueueMappingForm(request.POST)
    if not form.is_valid():
        error_messages = []
        for field_name, errors in form.errors.items():
            label = form.fields[field_name].label if field_name in form.fields else field_name
            error_messages.append(f"{label}: {', '.join(errors)}")
        messages.error(request, "Unable to map pod. " + " | ".join(error_messages))
        return redirect("dashboard:admin_pods")

    queue_name = form.cleaned_data["queue_name"]

    pod_endpoint_url = str(request.POST.get("pod_endpoint_url") or "").strip()
    mapped_endpoint_url = str(
        RunPodQueueMapping.objects.filter(pod_id=pod_id).values_list("endpoint_url", flat=True).first() or ""
    ).strip()
    endpoint_url = pod_endpoint_url or mapped_endpoint_url or get_queue_endpoint(queue_name, default="").strip()
    if not endpoint_url:
        messages.error(request, f"Queue '{queue_name}' has no endpoint available for automatic mapping.")
        return redirect("dashboard:admin_pods")

    pod_name = str(request.POST.get("pod_name") or "").strip()

    with transaction.atomic():
        RunPodQueueMapping.objects.filter(pod_id=pod_id).exclude(queue_name=queue_name).delete()
        RunPodQueueMapping.objects.update_or_create(
            queue_name=queue_name,
            defaults={
                "pod_id": pod_id,
                "pod_name": pod_name,
                "endpoint_url": endpoint_url,
            },
        )

    messages.success(request, f"Mapped queue '{queue_name}' to pod '{pod_id}'.")
    return redirect("dashboard:admin_pods")


@_superuser_required
def admin_pod_unmap(request, pod_id: str):
    if request.method != "POST":
        return redirect("dashboard:admin_pods")

    deleted, _ = RunPodQueueMapping.objects.filter(pod_id=pod_id).delete()
    if deleted:
        messages.success(request, f"Removed queue mapping for pod '{pod_id}'.")
    else:
        messages.info(request, f"No mapping found for pod '{pod_id}'.")
    return redirect("dashboard:admin_pods")


@_superuser_required
def admin_pod_action(request, pod_id: str):
    if request.method != "POST":
        return redirect("dashboard:admin_pods")

    action = str(request.POST.get("action") or "").strip().lower()

    try:
        if action == "pause":
            runpod_pods.pause_pod(pod_id)
            messages.success(request, f"Pod '{pod_id}' paused.")
        elif action == "resume":
            runpod_pods.resume_pod(pod_id)
            messages.success(request, f"Pod '{pod_id}' resumed.")
        elif action == "terminate":
            terminated = runpod_pods.terminate_pod(pod_id)
            if terminated.get("terminated"):
                messages.success(request, f"Pod '{pod_id}' terminated.")
            else:
                messages.info(request, f"Pod '{pod_id}' was already terminated.")
        else:
            messages.error(request, "Unknown pod action requested.")
    except runpod_pods.RunPodError as exc:
        messages.error(request, f"Unable to {action or 'run action on'} pod '{pod_id}': {exc}")

    return redirect("dashboard:admin_pods")


@_superuser_required
def admin_celery_status(request):
    status = get_celery_status()
    return TemplateResponse(
        request,
        "dashboard/site_admin/_celery_status.html",
        context={
            "celery": status,
            "status_refreshed_at": timezone.now(),
        },
    )
