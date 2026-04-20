from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.pore_analysis.models import AnalysisPricingRate, CreditTransaction

MILLION = Decimal("1000000")
TWO_PLACES = Decimal("0.01")


class NoPricingRateError(Exception):
    """Raised when no active pricing rate is configured for an analysis/backend."""


class InsufficientCreditsError(Exception):
    """Raised when a team does not have enough credits for a job."""


def _normalize_backend(backend: str | None) -> str:
    return (backend or "default").lower()


def get_team_credit_balance(team) -> Decimal:
    balance = CreditTransaction.objects.filter(team=team).aggregate(balance=Sum("amount"))["balance"]
    return balance if balance is not None else Decimal("0.00")


def get_pricing_rate(analysis_type: str, backend: str | None) -> AnalysisPricingRate:
    normalized_backend = _normalize_backend(backend)

    rate = (
        AnalysisPricingRate.objects.filter(
            analysis_type=analysis_type,
            backend=normalized_backend,
            is_active=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if rate:
        return rate

    fallback = (
        AnalysisPricingRate.objects.filter(
            analysis_type=analysis_type,
            backend="default",
            is_active=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if fallback:
        return fallback

    raise NoPricingRateError(
        f"No active pricing rate configured for analysis_type='{analysis_type}', backend='{normalized_backend}'."
    )


def calculate_estimated_credits(image, analysis_type: str, parameters: dict | None = None) -> Decimal:
    params = parameters or {}
    backend = params.get("backend", "default")

    rate = get_pricing_rate(analysis_type=analysis_type, backend=backend)
    voxels = Decimal(str(image.total_voxels))
    raw_cost = (voxels / MILLION) * rate.credits_per_million_voxels
    return raw_cost.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def ensure_sufficient_credits(team, required_credits: Decimal) -> None:
    available = get_team_credit_balance(team)
    if available < required_credits:
        raise InsufficientCreditsError(
            f"Insufficient credits. Required {required_credits}, available {available}."
        )


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
