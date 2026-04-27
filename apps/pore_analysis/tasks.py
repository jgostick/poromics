import logging
import os
from decimal import Decimal

import numpy as np
from celery import shared_task
from celery.signals import worker_process_init
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .analysis.pricing import refund_job_charge
from .models import AnalysisJob, AnalysisResult, JobStatus
from .queue_catalog import get_queue_backend, get_queue_endpoint

log = logging.getLogger(__name__)


def _format_job_error_message(exc: Exception) -> str:
    raw_message = str(exc).strip()
    message = raw_message or exc.__class__.__name__

    # Common on workers when S3-backed media is enabled but the service lacks AWS creds.
    if exc.__class__.__name__ == "NoCredentialsError" or "Unable to locate credentials" in message:
        return (
            "Storage credentials are missing on the worker. "
            "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY for this worker service, "
            "or disable USE_S3_MEDIA for this environment."
        )

    if isinstance(exc, FileNotFoundError) and "uploaded_images/" in message:
        return (
            "Uploaded image file was not found in storage. "
            "Verify USE_S3_MEDIA and AWS_STORAGE_BUCKET_NAME are the same on web and worker services."
        )

    return f"{exc.__class__.__name__}: {message}"


def _fail_job_with_refund(job: AnalysisJob, exc: Exception) -> None:
    log.exception(
        "Analysis job %s (%s) failed for image %s",
        job.id,
        job.analysis_type,
        job.image_id,
    )

    with transaction.atomic():
        job.status = JobStatus.FAILED
        job.completed_at = timezone.now()
        job.actual_cost = Decimal("0.00")
        job.error_message = _format_job_error_message(exc)
        job.save(update_fields=["status", "completed_at", "actual_cost", "error_message", "updated_at"])
        refund_job_charge(job, reason="job failed")


def _get_task_queue_name(task_request, default_queue: str) -> str:
    delivery_info = getattr(task_request, "delivery_info", None) or {}
    queue_name = delivery_info.get("routing_key")
    return str(queue_name or default_queue)


def _resolve_taichi_endpoint(queue_name: str) -> str:
    default_endpoint = getattr(settings, "TAICHI_DEFAULT_SERVER_URL", "")
    return get_queue_endpoint(queue_name, default=default_endpoint).strip()


def _resolve_julia_endpoint(queue_name: str) -> str:
    default_endpoint = getattr(settings, "JULIA_DEFAULT_SERVER_URL", "http://127.0.0.1:2999")
    return get_queue_endpoint(queue_name, default=default_endpoint)


def _resolve_cpu_endpoint(queue_name: str) -> str:
    return get_queue_endpoint(queue_name, default="").strip()


def _resolve_endpoint_for_job(job: AnalysisJob, queue_name: str, *, compute: str) -> str:
    """Resolve endpoint with per-job routing metadata taking precedence over settings.

    This prevents failures when workers are not restarted after queue catalog changes.
    """
    params = job.parameters or {}
    persisted_endpoint = str(params.get("endpoint_url") or "").strip()
    if persisted_endpoint:
        return persisted_endpoint

    if compute == "julia":
        return _resolve_julia_endpoint(queue_name)
    if compute == "taichi":
        return _resolve_taichi_endpoint(queue_name)
    return _resolve_cpu_endpoint(queue_name)


def _is_serverless_queue(queue_name: str) -> bool:
    """Return True if *queue_name* uses the RunPod Serverless path."""
    try:
        return get_queue_backend(queue_name) == "serverless"
    except Exception:
        return False


def _is_runpod_pod_queue(queue_name: str) -> bool:
    """Return True if *queue_name* uses the ephemeral RunPod pod path."""
    try:
        return get_queue_backend(queue_name) == "runpod-gpu"
    except Exception:
        return False


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_permeability_job(self, job_id):
    job = AnalysisJob.objects.select_related("image").get(id=job_id)

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.progress_percentage = 5
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "progress_percentage", "error_message", "updated_at"])

    try:
        queue_name = _get_task_queue_name(self.request, default_queue="kabs-cpu")

        if _is_serverless_queue(queue_name):
            # --- RunPod Serverless path ---
            # RunPod manages worker lifecycle; no pod creation or endpoint URL needed here.
            from .runpod_serverless_client import run_permeability_serverless

            with job.image.file.open("rb") as f:
                arr = np.load(f, allow_pickle=False)

            job.progress_percentage = 20
            job.save(update_fields=["progress_percentage", "updated_at"])

            solution = run_permeability_serverless(
                queue_name=queue_name,
                image_array=arr,
                direction=job.parameters["direction"],
                max_iterations=job.parameters["max_iterations"],
                tolerance=job.parameters["tolerance"],
                backend=job.parameters["backend"],
                voxel_size=float(job.image.voxel_size or 1.0),
            )

        elif _is_runpod_pod_queue(queue_name):
            # --- Ephemeral RunPod pod path ---
            # Create a fresh pod, run the job, terminate the pod immediately afterwards.
            from .runpod_orchestration import create_ephemeral_pod, terminate_ephemeral_pod

            pod_id, endpoint_url = create_ephemeral_pod(queue_name)
            try:
                with job.image.file.open("rb") as f:
                    arr = np.load(f, allow_pickle=False)

                job.progress_percentage = 20
                job.save(update_fields=["progress_percentage", "updated_at"])

                from .analysis.permeability import run_kabs_permeability

                solution = run_kabs_permeability(
                    image_array=arr,
                    direction=job.parameters["direction"],
                    max_iterations=job.parameters["max_iterations"],
                    tolerance=job.parameters["tolerance"],
                    backend=job.parameters["backend"],
                    voxel_size=float(job.image.voxel_size or 1.0),
                    endpoint_url=endpoint_url,
                )
            finally:
                terminate_ephemeral_pod(pod_id)

        else:
            # --- Local / CPU path ---
            with job.image.file.open("rb") as f:
                arr = np.load(f, allow_pickle=False)

            job.progress_percentage = 20
            job.save(update_fields=["progress_percentage", "updated_at"])

            from .analysis.permeability import run_kabs_permeability

            solution = run_kabs_permeability(
                image_array=arr,
                direction=job.parameters["direction"],
                max_iterations=job.parameters["max_iterations"],
                tolerance=job.parameters["tolerance"],
                backend=job.parameters["backend"],
                voxel_size=float(job.image.voxel_size or 1.0),
                endpoint_url=None,
            )

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            AnalysisResult.objects.update_or_create(
                job=job,
                defaults={
                    "metrics": {
                        "solution": solution,
                    }
                },
            )

            job.status = JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.actual_cost = job.estimated_cost
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "actual_cost", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        _fail_job_with_refund(job, exc)
        raise


@worker_process_init.connect
def init_taichi(**kwargs):
    import taichi as ti

    arch_map = {
        "cpu": ti.cpu,
        "gpu": ti.gpu,
        "metal": ti.metal,
        "cuda": ti.cuda,
        "opengl": ti.opengl,
    }
    backend = os.environ.get("TAICHI_BACKEND", "cpu")
    ti.init(arch=arch_map.get(backend, ti.cpu))


@shared_task(bind=True, autoretry_for=(), retry_kwargs={"max_retries": 0})
def run_diffusivity_job(self, job_id):
    """Execute a diffusivity calculation via the external Julia tortuosity service."""
    job = AnalysisJob.objects.select_related("image").get(id=job_id)

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.progress_percentage = 5
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "progress_percentage", "error_message", "updated_at"])

    try:
        queue_name = _get_task_queue_name(self.request, default_queue="julia-cpu")
        endpoint_url = _resolve_endpoint_for_job(job, queue_name, compute="julia")

        # Verify the Julia service is reachable before loading the array.
        # Julia runs as a persistent always-on server; checking reachability is a
        # meaningful pre-flight guard before charging the user.
        from julia_client import _server_healthy

        if not _server_healthy(endpoint_url):
            raise RuntimeError(f"Julia tortuosity service is unreachable for queue '{queue_name}' at {endpoint_url}.")

        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.diffusivity import run_julia_diffusivity

        solution = run_julia_diffusivity(
            image_array=arr,
            direction=job.parameters["direction"],
            tolerance=job.parameters["tolerance"],
            backend=job.parameters["backend"],
            endpoint_url=endpoint_url,
        )

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            AnalysisResult.objects.update_or_create(
                job=job,
                defaults={"metrics": {"solution": solution}},
            )
            job.status = JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.actual_cost = job.estimated_cost
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "actual_cost", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Diffusivity job %s failed", job_id)
        _fail_job_with_refund(job, exc)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_poresize_job(self, job_id):
    """Execute pore-size-distribution analysis on CPU workers."""
    job = AnalysisJob.objects.select_related("image").get(id=job_id)

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.progress_percentage = 5
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "progress_percentage", "error_message", "updated_at"])

    try:
        queue_name = _get_task_queue_name(self.request, default_queue="basic-cpu")
        endpoint_url = _resolve_endpoint_for_job(job, queue_name, compute="cpu")

        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.pore_size_distribution import run_poresize

        sizes = int((job.parameters or {}).get("sizes", 25))
        voxel_size = float(job.image.voxel_size or 1.0)
        solution = run_poresize(
            image_array=arr,
            sizes=sizes,
            voxel_size=voxel_size,
            endpoint_url=endpoint_url or None,
        )

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            AnalysisResult.objects.update_or_create(
                job=job,
                defaults={"metrics": {"solution": solution}},
            )
            job.status = JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.actual_cost = job.estimated_cost
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "actual_cost", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Pore-size job %s failed", job_id)
        _fail_job_with_refund(job, exc)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_network_extraction_job(self, job_id):
    """Execute pore-network extraction using porespy snow2 or magnet."""
    job = AnalysisJob.objects.select_related("image").get(id=job_id)

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.progress_percentage = 5
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "progress_percentage", "error_message", "updated_at"])

    try:
        queue_name = _get_task_queue_name(self.request, default_queue="network-cpu")
        endpoint_url = _resolve_endpoint_for_job(job, queue_name, compute="cpu")

        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.network_extraction import run_network_extraction, serialize_net_payload

        output = run_network_extraction(
            image_array=arr,
            params=job.parameters or {},
            voxel_size=float(job.image.voxel_size or 1.0),
            endpoint_url=endpoint_url or None,
        )
        net = output["net"]
        method = output["method"]

        pore_coords = net.get("pore.coords")
        throat_conns = net.get("throat.conns")
        pore_count = int(len(pore_coords)) if pore_coords is not None else 0
        throat_count = int(len(throat_conns)) if throat_conns is not None else 0

        payload_bytes = serialize_net_payload({"net": net})
        artifact_name = f"network_{job.id}.pkl"

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            result, _ = AnalysisResult.objects.update_or_create(
                job=job,
                defaults={
                    "metrics": {
                        "solution": {
                            "method": method,
                            "backend": (job.parameters or {}).get("backend"),
                            "pore_count": pore_count,
                            "throat_count": throat_count,
                            "network_artifact_format": "pickle/wrapper-with-net",
                        }
                    },
                },
            )
            result.network_file.save(artifact_name, ContentFile(payload_bytes), save=True)

            job.status = JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.actual_cost = job.estimated_cost
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "actual_cost", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Network extraction job %s failed", job_id)
        _fail_job_with_refund(job, exc)
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_network_validation_job(self, job_id):
    """Run OpenPNM StokesFlow and FickianDiffusion on a stored pore-network artifact."""
    job = AnalysisJob.objects.select_related("image").get(id=job_id)

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.progress_percentage = 5
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "progress_percentage", "error_message", "updated_at"])

    try:
        from .models import AnalysisResult as AR

        network_job_id = (job.parameters or {}).get("network_job_id")
        if not network_job_id:
            raise ValueError("Parameters missing 'network_job_id'.")

        source_result = AR.objects.select_related("job__image").get(job_id=network_job_id)
        net_dict = source_result.load_network_dict()
        if net_dict is None:
            raise ValueError(f"Network extraction job {network_job_id} has no stored network artifact.")

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.network_validation import run_network_validation

        solution = run_network_validation(
            net_dict=net_dict,
            params=job.parameters or {},
            image_shape=list(job.image.dimensions),
            voxel_size=float(job.image.voxel_size or 1.0),
        )

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            AnalysisResult.objects.update_or_create(
                job=job,
                defaults={"metrics": {"solution": solution}},
            )
            job.status = JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.actual_cost = job.estimated_cost
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "actual_cost", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Network validation job %s failed", job_id)
        _fail_job_with_refund(job, exc)
        raise


@shared_task(bind=True)
def cleanup_orphaned_ephemeral_pods(self):
    """Periodic Celery Beat task: terminate RunPod ephemeral pods that have outlived
    RUNPOD_POD_MAX_AGE_SECONDS (default 3600s / 1 hour).

    Protects against pods left running when a worker is killed before the finally block
    in run_permeability_job can call terminate_ephemeral_pod().

    Schedule this task via django-celery-beat or SCHEDULED_TASKS in settings.
    """
    from .runpod_orchestration import terminate_orphaned_ephemeral_pods

    try:
        count = terminate_orphaned_ephemeral_pods()
        log.info("Orphaned ephemeral pod cleanup: terminated %d pod(s)", count)
        return {"terminated": count}
    except Exception as exc:
        log.exception("Orphaned ephemeral pod cleanup failed: %s", exc)
        return {"terminated": 0, "error": str(exc)}
