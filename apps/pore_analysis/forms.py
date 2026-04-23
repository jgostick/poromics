from django import forms
from django.utils.translation import gettext_lazy as _

from .models import AnalysisJob, AnalysisType, JobStatus, UploadedImage
from .queue_catalog import (
    get_default_queue_for_analysis,
    get_parallel_queues_for_analysis,
    get_queue_backend,
    get_queue_choices_for_analysis,
    queue_supports_analysis,
)


def _set_queue_field_choices(form: forms.Form, *, field_name: str, analysis_type: str) -> None:
    queue_choices = get_queue_choices_for_analysis(analysis_type)
    form.fields[field_name].choices = queue_choices
    if queue_choices:
        form.fields[field_name].initial = get_default_queue_for_analysis(analysis_type)


def _derive_backend_for_queue(
    *, form: forms.Form, queue_name: str | None, analysis_type: str, field_name: str = "queue_name"
) -> str | None:
    if not queue_name:
        return None
    if not queue_supports_analysis(queue_name, analysis_type):
        form.add_error(field_name, _("Selected queue is not available for this analysis."))
        return None
    return get_queue_backend(queue_name)


class PermeabilityLaunchForm(forms.Form):
    DIRECTION_CHOICES = [
        ("x", _("X direction")),
        ("y", _("Y direction")),
        ("z", _("Z direction")),
    ]

    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    direction = forms.ChoiceField(
        choices=DIRECTION_CHOICES,
        label=_("Flow direction"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    max_iterations = forms.IntegerField(
        label=_("Maximum iterations"),
        min_value=1,
        initial=20_000,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    tolerance = forms.FloatField(
        label=_("Tolerance"),
        min_value=0.0,
        initial=1e-3,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "any"}),
    )
    queue_name = forms.ChoiceField(
        choices=(),
        label=_("Queue"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")
        _set_queue_field_choices(self, field_name="queue_name", analysis_type=AnalysisType.PERMEABILITY)

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        direction = cleaned.get("direction")
        queue_name = cleaned.get("queue_name")
        backend = _derive_backend_for_queue(
            form=self,
            queue_name=queue_name,
            analysis_type=AnalysisType.PERMEABILITY,
        )

        # Guard against selecting z-direction for 2D data
        if image and direction == "z" and len(image.dimensions) < 3:
            self.add_error("direction", _("Z direction requires a 3D image."))

        if backend:
            cleaned["backend"] = backend

        return cleaned

    def to_parameters(self):
        queue_name = self.cleaned_data["queue_name"]
        return {
            "direction": self.cleaned_data["direction"],
            "max_iterations": self.cleaned_data["max_iterations"],
            "tolerance": self.cleaned_data["tolerance"],
            "queue_name": queue_name,
            "backend": self.cleaned_data.get("backend") or get_queue_backend(queue_name),
        }


class DiffusivityLaunchForm(forms.Form):
    DIRECTION_CHOICES = [
        ("x", _("X direction")),
        ("y", _("Y direction")),
        ("z", _("Z direction")),
    ]

    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    direction = forms.ChoiceField(
        choices=DIRECTION_CHOICES,
        label=_("Direction"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    tolerance = forms.FloatField(
        label=_("Solver tolerance"),
        min_value=0.0,
        initial=1e-5,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "any"}),
    )
    queue_name = forms.ChoiceField(
        choices=(),
        label=_("Queue"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")
        _set_queue_field_choices(self, field_name="queue_name", analysis_type=AnalysisType.DIFFUSIVITY)

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        direction = cleaned.get("direction")
        queue_name = cleaned.get("queue_name")
        backend = _derive_backend_for_queue(
            form=self,
            queue_name=queue_name,
            analysis_type=AnalysisType.DIFFUSIVITY,
        )
        if image and direction == "z" and len(image.dimensions) < 3:
            self.add_error("direction", _("Z direction requires a 3D image."))
        if backend:
            cleaned["backend"] = backend
        return cleaned

    def to_parameters(self):
        queue_name = self.cleaned_data["queue_name"]
        return {
            "direction": self.cleaned_data["direction"],
            "tolerance": self.cleaned_data["tolerance"],
            "queue_name": queue_name,
            "backend": self.cleaned_data.get("backend") or get_queue_backend(queue_name),
        }


class PoreSizeLaunchForm(forms.Form):
    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    sizes = forms.IntegerField(
        label=_("Histogram bins"),
        min_value=2,
        initial=25,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    queue_name = forms.ChoiceField(
        choices=(),
        label=_("Queue"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")
        _set_queue_field_choices(self, field_name="queue_name", analysis_type=AnalysisType.PORESIZE)

    def clean(self):
        cleaned = super().clean()
        queue_name = cleaned.get("queue_name")
        backend = _derive_backend_for_queue(
            form=self,
            queue_name=queue_name,
            analysis_type=AnalysisType.PORESIZE,
        )
        if backend:
            cleaned["backend"] = backend
        return cleaned

    def to_parameters(self):
        queue_name = self.cleaned_data["queue_name"]
        return {
            "sizes": self.cleaned_data["sizes"],
            "queue_name": queue_name,
            "backend": self.cleaned_data.get("backend") or get_queue_backend(queue_name),
        }


class TrimImageForm(forms.Form):
    xmin = forms.IntegerField(widget=forms.HiddenInput())
    xmax = forms.IntegerField(widget=forms.HiddenInput())
    ymin = forms.IntegerField(widget=forms.HiddenInput())
    ymax = forms.IntegerField(widget=forms.HiddenInput())
    zmin = forms.IntegerField(widget=forms.HiddenInput())
    zmax = forms.IntegerField(widget=forms.HiddenInput())


class ImagePickerForm(forms.Form):
    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")


class NetworkExtractionLaunchForm(forms.Form):
    METHOD_CHOICES = [
        ("snow2", _("SNOW2")),
        ("magnet", _("MAGNET")),
    ]

    SNOW2_ACCURACY_CHOICES = [
        ("standard", _("Standard")),
        ("high", _("High")),
    ]

    MAGNET_THROAT_JUNCTION_CHOICES = [
        ("", _("None")),
        ("maximum filter", _("Maximum Filter")),
        ("fast marching", _("Fast Marching")),
    ]

    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        label=_("Extraction method"),
        initial="snow2",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    queue_name = forms.ChoiceField(
        choices=(),
        label=_("Queue"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    # snow2 fields
    boundary_width = forms.IntegerField(
        label=_("Boundary width (voxels)"),
        min_value=0,
        initial=3,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    accuracy = forms.ChoiceField(
        choices=SNOW2_ACCURACY_CHOICES,
        label=_("Accuracy"),
        initial="standard",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    sigma = forms.FloatField(
        label=_("Gaussian sigma"),
        min_value=0.0,
        initial=0.4,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "any"}),
    )
    r_max = forms.IntegerField(
        label=_("Peak filter radius (r_max)"),
        min_value=1,
        initial=4,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )

    # magnet fields
    surface = forms.BooleanField(
        label=_("Trim floating surface solids (3D only)"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )
    s = forms.IntegerField(
        label=_("Junction merge threshold (s)"),
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "placeholder": "Use default"}),
    )
    l_max = forms.IntegerField(
        label=_("Throat max-filter length (l_max)"),
        min_value=1,
        initial=7,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    throat_junctions = forms.ChoiceField(
        choices=MAGNET_THROAT_JUNCTION_CHOICES,
        required=False,
        label=_("Throat junction mode"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    throat_area = forms.BooleanField(
        label=_("Compute throat area"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "checkbox"}),
    )
    n_walkers = forms.IntegerField(
        label=_("Throat area walkers"),
        required=False,
        min_value=1,
        initial=10,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full"}),
    )
    step_size = forms.FloatField(
        label=_("Throat area step size"),
        required=False,
        min_value=0.0,
        initial=0.5,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "any"}),
    )
    max_n_steps = forms.IntegerField(
        label=_("Throat area max steps"),
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "placeholder": "Unlimited"}),
    )

    # parallel fields
    workers = forms.IntegerField(
        label=_("Workers (cores)"),
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "placeholder": "All available"}),
    )
    divs = forms.CharField(
        label=_("Chunk divisions per axis"),
        required=False,
        initial="2,2,2",
        help_text=_("Comma-separated values, for example 2,2,1"),
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )
    overlap = forms.IntegerField(
        label=_("Chunk overlap (voxels)"),
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "input input-bordered w-full", "placeholder": "Auto"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")
        _set_queue_field_choices(self, field_name="queue_name", analysis_type=AnalysisType.NETWORK_EXTRACTION)
        parallel_queues = sorted(get_parallel_queues_for_analysis(AnalysisType.NETWORK_EXTRACTION))
        self.fields["queue_name"].widget.attrs["data-parallel-queues"] = ",".join(parallel_queues)

    def _parse_divs(self, raw_divs: str):
        if not raw_divs:
            return None
        pieces = [piece.strip() for piece in raw_divs.split(",") if piece.strip()]
        if not pieces:
            return None
        try:
            parsed = [int(piece) for piece in pieces]
        except ValueError as exc:
            raise forms.ValidationError(_("Chunk divisions must be integers separated by commas.")) from exc
        if any(value < 1 for value in parsed):
            raise forms.ValidationError(_("Chunk divisions must all be at least 1."))
        return parsed

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("method")
        queue_name = cleaned.get("queue_name")
        image = cleaned.get("image")
        backend = _derive_backend_for_queue(
            form=self,
            queue_name=queue_name,
            analysis_type=AnalysisType.NETWORK_EXTRACTION,
        )
        if backend:
            cleaned["backend"] = backend

        # Parallel settings are required only for parallel backend
        if backend == "parallel":
            if cleaned.get("divs") in (None, ""):
                self.add_error("divs", _("Chunk divisions are required for parallel backend."))
            if cleaned.get("workers") in (None, ""):
                self.add_error("workers", _("Workers are required for parallel backend."))

            raw_divs = cleaned.get("divs")
            if raw_divs:
                parsed_divs = self._parse_divs(raw_divs)
                cleaned["divs_parsed"] = parsed_divs
                if image and parsed_divs and len(parsed_divs) != len(image.dimensions):
                    self.add_error(
                        "divs",
                        _("Chunk divisions must have %(count)s values for this image.")
                        % {"count": len(image.dimensions)},
                    )

        # throat area inputs are required only if throat area is enabled
        if method == "magnet" and cleaned.get("throat_area"):
            if cleaned.get("n_walkers") in (None, ""):
                self.add_error("n_walkers", _("Number of walkers is required when throat area is enabled."))
            if cleaned.get("step_size") in (None, ""):
                self.add_error("step_size", _("Step size is required when throat area is enabled."))

        return cleaned

    def to_parameters(self):
        method = self.cleaned_data["method"]
        queue_name = self.cleaned_data["queue_name"]
        backend = self.cleaned_data.get("backend") or get_queue_backend(queue_name)
        params = {
            "method": method,
            "queue_name": queue_name,
            "backend": backend,
        }

        if method == "snow2":
            params.update(
                {
                    "boundary_width": self.cleaned_data["boundary_width"],
                    "accuracy": self.cleaned_data["accuracy"],
                    "sigma": self.cleaned_data["sigma"],
                    "r_max": self.cleaned_data["r_max"],
                }
            )
        else:
            params.update(
                {
                    "surface": self.cleaned_data["surface"],
                    "s": self.cleaned_data.get("s"),
                    "l_max": self.cleaned_data["l_max"],
                    "throat_junctions": self.cleaned_data.get("throat_junctions") or None,
                    "throat_area": self.cleaned_data.get("throat_area", False),
                }
            )
            if self.cleaned_data.get("throat_area"):
                params.update(
                    {
                        "n_walkers": self.cleaned_data.get("n_walkers"),
                        "step_size": self.cleaned_data.get("step_size"),
                        "max_n_steps": self.cleaned_data.get("max_n_steps"),
                    }
                )

        if backend == "parallel":
            params["parallel_kw"] = {
                "cores": self.cleaned_data.get("workers"),
                "divs": self.cleaned_data.get("divs_parsed") or self._parse_divs(self.cleaned_data.get("divs", "")),
                "overlap": self.cleaned_data.get("overlap"),
            }
        else:
            params["parallel_kw"] = None

        return params


class NetworkValidationLaunchForm(forms.Form):
    DIRECTION_CHOICES = [
        ("x", _("X direction")),
        ("y", _("Y direction")),
        ("z", _("Z direction")),
    ]

    SHAPE_MODEL_CHOICES = [
        ("balls_and_sticks", _("Balls and Sticks")),
        ("circles_and_rectangles", _("Circles and Rectangles")),
        ("cones_and_cylinders", _("Cones and Cylinders")),
        ("pyramids_and_cuboids", _("Pyramids and Cuboids")),
        ("squares_and_cubes", _("Squares and Cubes")),
    ]

    image = forms.ModelChoiceField(
        queryset=UploadedImage.objects.none(),
        label=_("Image"),
        empty_label=_("Select an image"),
        widget=forms.Select(
            attrs={
                "class": "select select-bordered w-full",
                "hx-get": "",  # set dynamically in template
                "hx-target": "#network-job-options",
                "hx-trigger": "change",
                "hx-include": "this",
            }
        ),
    )
    network_job = forms.ModelChoiceField(
        queryset=AnalysisJob.objects.none(),
        label=_("Extracted network"),
        empty_label=_("Select a network extraction job"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full", "id": "id_network_job"}),
    )
    direction = forms.ChoiceField(
        choices=DIRECTION_CHOICES,
        label=_("Flow direction"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    queue_name = forms.ChoiceField(
        choices=(),
        label=_("Queue"),
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )
    pore_diameter_key = forms.CharField(
        label=_("Pore diameter key"),
        initial="pore.equivalent_diameter",
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )
    throat_diameter_key = forms.CharField(
        label=_("Throat diameter key"),
        initial="throat.equivalent_diameter",
        widget=forms.TextInput(attrs={"class": "input input-bordered w-full"}),
    )
    shape_model = forms.ChoiceField(
        choices=SHAPE_MODEL_CHOICES,
        label=_("Geometry shape model"),
        initial="balls_and_sticks",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")
        _set_queue_field_choices(self, field_name="queue_name", analysis_type=AnalysisType.NETWORK_VALIDATION)

        # Pre-populate network_job based on submitted image (handles POST validation)
        image_id = self.data.get("image") if self.data else None
        if image_id:
            self.fields["network_job"].queryset = (
                AnalysisJob.objects.filter(
                    team=team,
                    image_id=image_id,
                    analysis_type=AnalysisType.NETWORK_EXTRACTION,
                    status=JobStatus.COMPLETED,
                    result__network_file__isnull=False,
                )
                .exclude(
                    result__network_file="",
                )
                .order_by("-created_at")
            )
        else:
            self.fields["network_job"].queryset = AnalysisJob.objects.none()

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        direction = cleaned.get("direction")
        queue_name = cleaned.get("queue_name")
        backend = _derive_backend_for_queue(
            form=self,
            queue_name=queue_name,
            analysis_type=AnalysisType.NETWORK_VALIDATION,
        )
        if image and direction == "z" and len(image.dimensions) < 3:
            self.add_error("direction", _("Z direction requires a 3D image."))
        if backend:
            cleaned["backend"] = backend
        return cleaned

    def to_parameters(self):
        queue_name = self.cleaned_data["queue_name"]
        return {
            "network_job_id": str(self.cleaned_data["network_job"].id),
            "direction": self.cleaned_data["direction"],
            "queue_name": queue_name,
            "backend": self.cleaned_data.get("backend") or get_queue_backend(queue_name),
            "pore_diameter_key": self.cleaned_data["pore_diameter_key"].strip(),
            "throat_diameter_key": self.cleaned_data["throat_diameter_key"].strip(),
            "shape_model": self.cleaned_data["shape_model"],
        }
