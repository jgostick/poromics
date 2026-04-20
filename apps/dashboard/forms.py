from django import forms

from apps.users.models import CustomUser


class DateRangeForm(forms.Form):
    start = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))


class AdminJobFilterForm(forms.Form):
    STATUS_CHOICES = [("", "All Statuses")] + [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]
    ANALYSIS_TYPE_CHOICES = [("", "All Types")] + [
        ("network_extraction", "Pore Network Extraction"),
        ("network_validation", "Network Validation"),
        ("permeability", "Permeability"),
        ("diffusivity", "Diffusivity"),
        ("morphology", "Morphological Analysis"),
        ("poresize", "Pore Size Distribution"),
        ("visualization", "3D Visualization"),
        ("full_suite", "Complete Analysis Suite"),
    ]

    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False)
    analysis_type = forms.ChoiceField(choices=ANALYSIS_TYPE_CHOICES, required=False)
    team = forms.ChoiceField(choices=[], required=False)
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        from apps.teams.models import Team

        super().__init__(*args, **kwargs)
        team_choices = [("", "All Teams")] + [(str(t.id), t.name) for t in Team.objects.order_by("name")]
        self.fields["team"].choices = team_choices


class AdminCreditGrantForm(forms.Form):
    team = forms.ChoiceField(
        choices=[],
        label="Team",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    user = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        label="User",
        empty_label="Use current admin user",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    amount = forms.DecimalField(
        min_value=0.01,
        decimal_places=2,
        max_digits=8,
        initial=10,
        label="Credits",
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.01"}),
    )
    description = forms.CharField(
        max_length=200,
        initial="Admin credit grant",
        label="Description",
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )

    def __init__(self, *args, **kwargs):
        from apps.teams.models import Membership, Team

        super().__init__(*args, **kwargs)
        self.fields["team"].choices = [(str(team.id), team.name) for team in Team.objects.order_by("name")]
        self.fields["user"].queryset = CustomUser.objects.order_by("email")

        team_id = self.data.get("team") or self.initial.get("team")
        if team_id:
            member_ids = Membership.objects.filter(team_id=team_id).values_list("user_id", flat=True)
            self.fields["user"].queryset = CustomUser.objects.filter(id__in=member_ids).order_by("email")

    def clean(self):
        from apps.teams.models import Membership

        cleaned = super().clean()
        team_id = cleaned.get("team")
        user = cleaned.get("user")

        if team_id and user:
            is_member = Membership.objects.filter(team_id=team_id, user=user).exists()
            if not is_member:
                self.add_error("user", "Selected user is not a member of the selected team.")

        return cleaned
