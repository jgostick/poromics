import os
import logging
from celery import shared_task
from celery.signals import worker_process_init
from django.utils import timezone
from django.db import transaction
import numpy as np
from .models import AnalysisJob, AnalysisResult, JobStatus

log = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 1})
def run_permeability_job(self, job_id):
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

        # Keep kabs call in a dedicated analysis module
        from .analysis.permeability import run_kabs_permeability

        solution = run_kabs_permeability(
            image_array=arr,
            direction=job.parameters["direction"],
            max_iterations=job.parameters["max_iterations"],
            tolerance=job.parameters["tolerance"],
            backend=job.parameters["backend"],
            voxel_size=job.image.voxel_size,
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
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        job.status = JobStatus.FAILED
        job.completed_at = timezone.now()
        job.error_message = str(exc)
        job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
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
        # Verify the Julia service is reachable before loading the array.
        from julia_client import _server_healthy
        if not _server_healthy():
            raise RuntimeError(
                "Julia tortuosity service is not running or unreachable. "
                "Start it with: julia julia_server.jl"
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
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Diffusivity job %s failed", job_id)
        job.status = JobStatus.FAILED
        job.completed_at = timezone.now()
        job.error_message = str(exc)
        job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
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
            job.progress_percentage = 100
            job.save(update_fields=["status", "completed_at", "progress_percentage", "updated_at"])

        return {"job_id": str(job.id), "status": "completed"}

    except Exception as exc:
        log.exception("Pore-size job %s failed", job_id)
        job.status = JobStatus.FAILED
        job.completed_at = timezone.now()
        job.error_message = str(exc)
        job.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
        raise
