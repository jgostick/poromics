from django import forms


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
