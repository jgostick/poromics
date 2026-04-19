from django import forms
from django.utils.translation import gettext_lazy as _

from .models import UploadedImage


class PermeabilityLaunchForm(forms.Form):
    DIRECTION_CHOICES = [
        ("x", _("X direction")),
        ("y", _("Y direction")),
        ("z", _("Z direction")),
    ]

    BACKEND_CHOICES = [
        ("cpu", _("CPU")),
        ("gpu", _("GPU")),
        ("metal", _("Metal")),
        ("cuda", _("CUDA")),
        ("opengl", _("OpenGL")),
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
    backend = forms.ChoiceField(
        choices=BACKEND_CHOICES,
        label=_("Backend"),
        initial="cpu",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        direction = cleaned.get("direction")

        # Guard against selecting z-direction for 2D data
        if image and direction == "z" and len(image.dimensions) < 3:
            self.add_error("direction", _("Z direction requires a 3D image."))

        return cleaned

    def to_parameters(self):
        return {
            "direction": self.cleaned_data["direction"],
            "max_iterations": self.cleaned_data["max_iterations"],
            "tolerance": self.cleaned_data["tolerance"],
            "backend": self.cleaned_data["backend"],
        }
    

class DiffusivityLaunchForm(forms.Form):
    DIRECTION_CHOICES = [
        ("x", _("X direction")),
        ("y", _("Y direction")),
        ("z", _("Z direction")),
    ]

    BACKEND_CHOICES = [
        ("cpu", _("CPU")),
        ("gpu", _("GPU")),
        ("metal", _("Metal")),
        ("cuda", _("CUDA")),
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
    backend = forms.ChoiceField(
        choices=BACKEND_CHOICES,
        label=_("Backend"),
        initial="cpu",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        direction = cleaned.get("direction")
        if image and direction == "z" and len(image.dimensions) < 3:
            self.add_error("direction", _("Z direction requires a 3D image."))
        return cleaned

    def to_parameters(self):
        return {
            "direction": self.cleaned_data["direction"],
            "tolerance": self.cleaned_data["tolerance"],
            "backend": self.cleaned_data["backend"],
        }


class PoreSizeLaunchForm(forms.Form):
    BACKEND_CHOICES = [
        ("cpu", _("CPU")),
    ]

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
    backend = forms.ChoiceField(
        choices=BACKEND_CHOICES,
        label=_("Backend"),
        initial="cpu",
        widget=forms.Select(attrs={"class": "select select-bordered w-full"}),
    )

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = UploadedImage.objects.filter(team=team).order_by("-created_at")

    def to_parameters(self):
        return {
            "sizes": self.cleaned_data["sizes"],
            "backend": self.cleaned_data["backend"],
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
        