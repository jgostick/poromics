from django.shortcuts import render

from apps.pore_analysis.analysis.pricing import get_team_credit_balance
from apps.pore_analysis.models import CreditTransaction
from apps.teams.decorators import login_and_team_required


@login_and_team_required
def credit_dashboard(request, team_slug):
    """Show credit balance and transaction history."""
    transactions = CreditTransaction.objects.filter(team=request.team).select_related(
        "user",
        "analysis_job",
    ).order_by("-created_at")
    credit_balance = get_team_credit_balance(request.team)

    context = {
        'transactions': transactions,
        'credit_balance': credit_balance,
        'team_slug': request.team.slug,
    }
    return render(request, 'pore_analysis/credit_dashboard.html', context)


def pricing(request):
    """Public pricing page."""
    return render(request, 'pore_analysis/pricing.html')
