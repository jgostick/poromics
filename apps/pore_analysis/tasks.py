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

log = logging.getLogger(__name__)


def _fail_job_with_refund(job: AnalysisJob, exc: Exception) -> None:
    with transaction.atomic():
        job.status = JobStatus.FAILED
        job.completed_at = timezone.now()
        job.actual_cost = Decimal("0.00")
        job.error_message = str(exc)
        job.save(update_fields=["status", "completed_at", "actual_cost", "error_message", "updated_at"])
        refund_job_charge(job, reason="job failed")


def _get_task_queue_name(task_request, default_queue: str) -> str:
    delivery_info = getattr(task_request, "delivery_info", None) or {}
    queue_name = delivery_info.get("routing_key")
    return str(queue_name or default_queue)


def _resolve_taichi_endpoint(queue_name: str) -> str:
    queue_endpoints = getattr(settings, "TAICHI_QUEUE_ENDPOINTS", {})
    default_endpoint = getattr(settings, "TAICHI_DEFAULT_SERVER_URL", "")
    return str(queue_endpoints.get(queue_name, default_endpoint)).strip()


def _resolve_julia_endpoint(queue_name: str) -> str:
    queue_endpoints = getattr(settings, "JULIA_QUEUE_ENDPOINTS", {})
    default_endpoint = getattr(settings, "JULIA_DEFAULT_SERVER_URL", "http://127.0.0.1:2999")
    return str(queue_endpoints.get(queue_name, default_endpoint))


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
        endpoint_url = _resolve_taichi_endpoint(queue_name)

        if endpoint_url:
            from taichi_client import _server_healthy as _taichi_server_healthy

            if not _taichi_server_healthy(endpoint_url):
                raise RuntimeError(
                    f"Taichi permeability service is unreachable for queue '{queue_name}' "
                    f"at {endpoint_url}."
                )

        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        # Keep kabs call in a dedicated analysis module
        from .analysis.permeability import run_kabs_permeability

        solution = run_kabs_permeability(
            image_array=arr,
            direction=job.parameters["direction"],
            max_iterations=job.parameters["max_iterations"],
            tolerance=job.parameters["tolerance"],
            backend=job.parameters["backend"],
            voxel_size=job.image.voxel_size,
            endpoint_url=endpoint_url or None,
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
        'cpu': ti.cpu,
        'gpu': ti.gpu,
        'metal': ti.metal,
        'cuda': ti.cuda,
        'opengl': ti.opengl,
    }
    backend = os.environ.get('TAICHI_BACKEND', 'cpu')
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
        endpoint_url = _resolve_julia_endpoint(queue_name)

        # Verify the Julia service is reachable before loading the array.
        from julia_client import _server_healthy
        if not _server_healthy(endpoint_url):
            raise RuntimeError(
                f"Julia tortuosity service is unreachable for queue '{queue_name}' "
                f"at {endpoint_url}."
            )

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
        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.pore_size_distribution import run_poresize

        sizes = int((job.parameters or {}).get("sizes", 25))
        voxel_size = float(job.image.voxel_size or 1.0)
        histogram = run_poresize(
            image_array=arr,
            sizes=sizes,
            voxel_size=voxel_size,
        )

        counts, bin_edges = histogram
        result = {
            "counts": counts.tolist(),
            "bin_edges": bin_edges.tolist(),
            "sizes": sizes,
            "voxel_size": voxel_size,
        }

        job.progress_percentage = 90
        job.save(update_fields=["progress_percentage", "updated_at"])

        with transaction.atomic():
            AnalysisResult.objects.update_or_create(
                job=job,
                defaults={"metrics": {"solution": result}},
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
        with job.image.file.open("rb") as f:
            arr = np.load(f, allow_pickle=False)

        job.progress_percentage = 20
        job.save(update_fields=["progress_percentage", "updated_at"])

        from .analysis.network_extraction import run_network_extraction, serialize_net_payload

        output = run_network_extraction(
            image_array=arr,
            params=job.parameters or {},
            voxel_size=float(job.image.voxel_size or 1.0),
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

