from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.pore_analysis.models import CreditTransaction
from apps.pore_analysis.queue_catalog import (
    QueueCatalogError,
    QueuePricingNotConfiguredError,
    get_default_queue_for_analysis,
    get_queue_pricing_rate,
)

MILLION = Decimal("1000000")
TWO_PLACES = Decimal("0.01")


class NoPricingRateError(Exception):
    """Raised when no pricing rate is configured for an analysis/queue."""


class InsufficientCreditsError(Exception):
    """Raised when a team does not have enough credits for a job."""


def _resolve_queue_name(analysis_type: str, parameters: dict | None) -> str:
    params = parameters or {}
    queue_name = str(params.get("queue_name") or "").strip()
    if queue_name:
        return queue_name

    try:
        return get_default_queue_for_analysis(analysis_type)
    except QueueCatalogError as exc:
        raise NoPricingRateError(f"No default queue configured for analysis_type='{analysis_type}'.") from exc


def get_team_credit_balance(team) -> Decimal:
    balance = CreditTransaction.objects.filter(team=team).aggregate(balance=Sum("amount"))["balance"]
    return balance if balance is not None else Decimal("0.00")


def get_pricing_rate(analysis_type: str, queue_name: str) -> Decimal:
    try:
        return get_queue_pricing_rate(queue_name=queue_name, analysis_type=analysis_type)
    except (QueueCatalogError, QueuePricingNotConfiguredError) as exc:
        raise NoPricingRateError(
            f"No active pricing rate configured for analysis_type='{analysis_type}', queue='{queue_name}'."
        ) from exc


def calculate_estimated_credits(image, analysis_type: str, parameters: dict | None = None) -> Decimal:
    queue_name = _resolve_queue_name(analysis_type=analysis_type, parameters=parameters)
    rate = get_pricing_rate(analysis_type=analysis_type, queue_name=queue_name)
    voxels = Decimal(str(image.total_voxels))
    raw_cost = (voxels / MILLION) * rate
    return raw_cost.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def ensure_sufficient_credits(team, required_credits: Decimal) -> None:
    available = get_team_credit_balance(team)
    if available < required_credits:
        raise InsufficientCreditsError(f"Insufficient credits. Required {required_credits}, available {available}.")


def charge_job_upfront(job) -> CreditTransaction:
    return CreditTransaction.objects.create(
        team=job.team,
        user=job.started_by,
        transaction_type="usage",
        amount=-job.estimated_cost,
        analysis_job=job,
        description=f"{job.get_analysis_type_display()} job charge",
    )


def refund_job_charge(job, reason: str) -> CreditTransaction | None:
    if not job.estimated_cost or job.estimated_cost <= Decimal("0.00"):
        return None

    existing_refund = CreditTransaction.objects.filter(
        team=job.team,
        analysis_job=job,
        transaction_type="refund",
    ).first()
    if existing_refund:
        return existing_refund

    return CreditTransaction.objects.create(
        team=job.team,
        user=job.started_by,
        transaction_type="refund",
        amount=job.estimated_cost,
        analysis_job=job,
        description=f"Refund for {job.get_analysis_type_display()} job: {reason}",
    )
