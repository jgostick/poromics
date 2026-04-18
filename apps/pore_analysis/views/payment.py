from django.db.models import Sum
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.pore_analysis.models import CreditTransaction
from apps.teams.decorators import login_and_team_required


@login_and_team_required
def credit_dashboard(request, team_slug):
    """Show credit balance and transaction history."""
    transactions = CreditTransaction.objects.filter(team=request.team).order_by('-created_at')
    
    # Calculate balance
    credit_balance = transactions.aggregate(balance=Sum('amount'))['balance'] or 0
    
    context = {
        'transactions': transactions,
        'credit_balance': credit_balance,
    }
    return render(request, 'pore_analysis/credit_dashboard.html', context)


def pricing(request):
    """Public pricing page."""
    return render(request, 'pore_analysis/pricing.html')
