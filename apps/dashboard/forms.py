from django import forms
from django.conf import settings

from apps.pore_analysis.queue_catalog import get_runpod_queue_choices
from apps.users.models import CustomUser
from apps.utils.runpod_pods import RunPodValidationError, parse_env_entries, parse_port_mappings


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


class AdminRunPodCreateForm(forms.Form):
    pod_name = forms.CharField(
        max_length=80,
        label="Pod name",
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )
    image_name = forms.CharField(
        max_length=255,
        required=False,
        label="Image",
        help_text="Optional. Leave blank to use RunPod's default image.",
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )
    compute_type = forms.ChoiceField(
        choices=[],
        label="Compute type",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    gpu_type_id = forms.ChoiceField(
        choices=[],
        required=False,
        label="GPU type",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    cpu_flavor_id = forms.ChoiceField(
        choices=[],
        required=False,
        label="CPU flavor",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    data_center_id = forms.ChoiceField(
        choices=[],
        required=False,
        label="Data center",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    cloud_type = forms.ChoiceField(
        choices=[],
        label="Cloud type",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    interruptible = forms.BooleanField(
        required=False,
        label="Interruptible",
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )
    ports = forms.CharField(
        required=False,
        label="Ports",
        help_text="One mapping per line, example: 8888/http",
        widget=forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
    )
    env_vars = forms.CharField(
        required=False,
        label="Environment",
        help_text="One KEY=VALUE per line",
        widget=forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 4}),
    )

    def __init__(self, *args, creation_options: dict | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        options = creation_options or {}

        compute_types = options.get("compute_types") or ["GPU", "CPU"]
        cloud_types = options.get("cloud_types") or ["SECURE", "COMMUNITY"]

        self.fields["compute_type"].choices = [(value, value) for value in compute_types]
        self.fields["cloud_type"].choices = [(value, value) for value in cloud_types]
        self.fields["gpu_type_id"].choices = [("", "Select GPU type")] + [
            (value, value) for value in options.get("gpu_type_ids", [])
        ]
        self.fields["cpu_flavor_id"].choices = [("", "Select CPU flavor")] + [
            (value, value) for value in options.get("cpu_flavor_ids", [])
        ]
        self.fields["data_center_id"].choices = [("", "Any data center")] + [
            (value, value) for value in options.get("data_center_ids", [])
        ]

        self.fields["compute_type"].initial = options.get(
            "default_compute_type",
            getattr(settings, "RUNPOD_DEFAULT_COMPUTE_TYPE", "GPU"),
        )
        self.fields["cloud_type"].initial = options.get(
            "default_cloud_type",
            getattr(settings, "RUNPOD_DEFAULT_CLOUD_TYPE", "SECURE"),
        )

        default_ports = getattr(settings, "RUNPOD_DEFAULT_PORTS", ["8888/http", "22/tcp"])
        if isinstance(default_ports, list):
            self.fields["ports"].initial = "\n".join(str(item) for item in default_ports)

    def clean(self):
        cleaned = super().clean()
        compute_type = str(cleaned.get("compute_type") or "").upper()
        gpu_type_id = str(cleaned.get("gpu_type_id") or "").strip()
        cpu_flavor_id = str(cleaned.get("cpu_flavor_id") or "").strip()

        if compute_type == "GPU" and not gpu_type_id:
            self.add_error("gpu_type_id", "GPU type is required when compute type is GPU.")
        if compute_type == "CPU" and not cpu_flavor_id:
            self.add_error("cpu_flavor_id", "CPU flavor is required when compute type is CPU.")

        try:
            cleaned["parsed_ports"] = parse_port_mappings(cleaned.get("ports"))
        except RunPodValidationError as exc:
            self.add_error("ports", str(exc))

        try:
            cleaned["parsed_env"] = parse_env_entries(cleaned.get("env_vars"))
        except RunPodValidationError as exc:
            self.add_error("env_vars", str(exc))

        return cleaned


class AdminRunPodQueueMappingForm(forms.Form):
    queue_name = forms.ChoiceField(
        choices=[],
        label="Queue",
        widget=forms.Select(attrs={"class": "select select-bordered select-xs w-full"}),
    )
    endpoint_url = forms.URLField(
        required=False,
        label="Endpoint",
        widget=forms.URLInput(
            attrs={"class": "input input-bordered input-xs w-full", "placeholder": "https://<runpod-host>"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._queue_choices = get_runpod_queue_choices()
        self.fields["queue_name"].choices = self._queue_choices

    def clean_queue_name(self) -> str:
        queue_name = str(self.cleaned_data.get("queue_name") or "").strip()
        allowed = {queue for queue, _ in self._queue_choices}
        if queue_name not in allowed:
            raise forms.ValidationError("Select a valid RunPod queue.")
        return queue_name

    def clean_endpoint_url(self) -> str:
        return str(self.cleaned_data.get("endpoint_url") or "").strip()
