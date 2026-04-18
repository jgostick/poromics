from io import BytesIO

import numpy as np
import porespy as ps
from django.contrib import messages
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.pore_analysis.forms import ImagePickerForm, TrimImageForm
from apps.pore_analysis.models import UploadedImage
from apps.teams.decorators import login_and_team_required

from .utils import get_pore_analysis_context


@login_and_team_required
def trim_image(request, team_slug):
    """Trim a 3D image by selecting bounds on X/Y/Z axes."""
    selected_image = None
    bounds_form = TrimImageForm()

    # GET: image picker (dropdown)
    picker_form = ImagePickerForm(request.team, request.GET or None)
    if picker_form.is_bound and picker_form.is_valid():
        selected_image = picker_form.cleaned_data["image"]

    # POST: apply trim
    if request.method == "POST":
        picker_form = ImagePickerForm(request.team, request.POST)
        bounds_form = TrimImageForm(request.POST)

        if picker_form.is_valid() and bounds_form.is_valid():
            selected_image = picker_form.cleaned_data["image"]

            xmin = bounds_form.cleaned_data["xmin"]
            xmax = bounds_form.cleaned_data["xmax"]
            ymin = bounds_form.cleaned_data["ymin"]
            ymax = bounds_form.cleaned_data["ymax"]
            zmin = bounds_form.cleaned_data["zmin"]
            zmax = bounds_form.cleaned_data["zmax"]

            with selected_image.file.open("rb") as f:
                arr = np.load(f, allow_pickle=False)

            if arr.ndim == 2:
                trimmed_array = arr[xmin:xmax, ymin:ymax]
            else:
                trimmed_array = arr[xmin:xmax, ymin:ymax, zmin:zmax]

            # Save trimmed as new image
            buffer = BytesIO()
            np.save(buffer, trimmed_array, allow_pickle=False)
            file_bytes = buffer.getvalue()

            new_name = f"{selected_image.name}_trimmed.npy"
            uploaded_image = UploadedImage.objects.create(
                team=request.team,
                uploaded_by=request.user,
                name=new_name,
                description=f"Trimmed from {selected_image.name}",
                file=ContentFile(file_bytes, name=new_name),
                file_size=len(file_bytes),
                dimensions=list(trimmed_array.shape),
                voxel_size=selected_image.voxel_size,
            )

            messages.success(request, _("Image trimmed and saved as '{}'.").format(new_name))
            return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=uploaded_image.id)

    context = {
        "picker_form": picker_form,
        "bounds_form": bounds_form,
        "image": selected_image,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/trim_image.html", context)


@login_and_team_required
def trim_image_preview(request, team_slug):
    """AJAX endpoint to preview trim bounds on original slices."""
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    image_id = request.POST.get("image_id")
    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)

    with image.file.open("rb") as f:
        arr = np.load(f, allow_pickle=False).astype(np.uint8)

    if arr.ndim == 2:
        arr = arr[:, :, np.newaxis]

    max_x, max_y, max_z = arr.shape

    xmin = max(0, min(int(request.POST.get("xmin", 0)), max_x - 1))
    xmax = max(xmin + 1, min(int(request.POST.get("xmax", max_x)), max_x))
    ymin = max(0, min(int(request.POST.get("ymin", 0)), max_y - 1))
    ymax = max(ymin + 1, min(int(request.POST.get("ymax", max_y)), max_y))
    zmin = max(0, min(int(request.POST.get("zmin", 0)), max_z - 1))
    zmax = max(zmin + 1, min(int(request.POST.get("zmax", max_z)), max_z))

    x_mid = (xmin + xmax - 1) // 2
    y_mid = (ymin + ymax - 1) // 2
    z_mid = (zmin + zmax - 1) // 2

    xy = arr[:, :, z_mid].T
    x_xy = np.arange(max_x)
    y_xy = np.arange(max_y)

    xz = arr[:, y_mid, :].T
    x_xz = np.arange(max_x)
    y_xz = np.arange(max_z)

    yz = arr[x_mid, :, :].T
    x_yz = np.arange(max_y)
    y_yz = np.arange(max_z)

    fig = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=("XY (Z mid)", "XZ (Y mid)", "YZ (X mid)"),
        horizontal_spacing=0.06,
    )

    def add_panel(z_data, x_vals, y_vals, row, col):
        z_min = float(np.min(z_data))
        z_max = float(np.max(z_data))
        if z_max <= z_min:
            z_max = z_min + 1.0

        fig.add_trace(
            go.Heatmap(
                z=z_data,
                x=x_vals,
                y=y_vals,
                colorscale="Gray",
                zmin=z_min,
                zmax=z_max,
                zsmooth=False,
                showscale=False,
                hovertemplate="x=%{x}, y=%{y}, value=%{z}<extra></extra>",
            ),
            row=row,
            col=col,
        )

    add_panel(xy, x_xy, y_xy, 1, 1)
    add_panel(xz, x_xz, y_xz, 1, 2)
    add_panel(yz, x_yz, y_yz, 1, 3)

    def add_vline(col, x, y0, y1):
        fig.add_trace(
            go.Scatter(
                x=[x, x],
                y=[y0, y1],
                mode="lines",
                line=dict(color="#ef4444", width=2, dash="dash"),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=col,
        )

    def add_hline(col, x0, x1, y):
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y, y],
                mode="lines",
                line=dict(color="#ef4444", width=2, dash="dash"),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=col,
        )

    bxmin, bxmax = xmin - 0.5, xmax - 0.5
    bymin, bymax = ymin - 0.5, ymax - 0.5
    bzmin, bzmax = zmin - 0.5, zmax - 0.5

    add_vline(1, bxmin, -0.5, max_y - 0.5)
    add_vline(1, bxmax, -0.5, max_y - 0.5)
    add_hline(1, -0.5, max_x - 0.5, bymin)
    add_hline(1, -0.5, max_x - 0.5, bymax)

    add_vline(2, bxmin, -0.5, max_z - 0.5)
    add_vline(2, bxmax, -0.5, max_z - 0.5)
    add_hline(2, -0.5, max_x - 0.5, bzmin)
    add_hline(2, -0.5, max_x - 0.5, bzmax)

    add_vline(3, bymin, -0.5, max_z - 0.5)
    add_vline(3, bymax, -0.5, max_z - 0.5)
    add_hline(3, -0.5, max_y - 0.5, bzmin)
    add_hline(3, -0.5, max_y - 0.5, bzmax)

    fig.update_xaxes(range=[-0.5, max_x - 0.5], row=1, col=1, constrain="domain", fixedrange=True)
    fig.update_yaxes(range=[max_y - 0.5, -0.5], row=1, col=1, scaleanchor="x", scaleratio=1, fixedrange=True)

    fig.update_xaxes(range=[-0.5, max_x - 0.5], row=1, col=2, constrain="domain", fixedrange=True)
    fig.update_yaxes(range=[max_z - 0.5, -0.5], row=1, col=2, scaleanchor="x2", scaleratio=1, fixedrange=True)

    fig.update_xaxes(range=[-0.5, max_y - 0.5], row=1, col=3, constrain="domain", fixedrange=True)
    fig.update_yaxes(range=[max_z - 0.5, -0.5], row=1, col=3, scaleanchor="x3", scaleratio=1, fixedrange=True)

    fig.update_layout(
        template="plotly_white",
        margin=dict(l=10, r=10, t=40, b=10),
        autosize=False,
        width=1100,
        height=380,
    )

    plot_html = pio.to_html(
        fig,
        include_plotlyjs=False,
        full_html=False,
        div_id="trim-plot",
        config={"responsive": False, "displayModeBar": False},
    )

    return render(
        request,
        "pore_analysis/components/trim_preview.html",
        {
            "plot_html": plot_html,
            "trimmed_shape": (xmax - xmin, ymax - ymin, zmax - zmin),
        },
    )


@login_and_team_required
def process_image(request, team_slug):
    """Apply pore-processing operations to a selected uploaded image."""
    images = UploadedImage.objects.filter(team=request.team).order_by("-created_at")

    if request.method == "POST":
        image_id = request.POST.get("image_id")
        image = get_object_or_404(UploadedImage, id=image_id, team=request.team)

        if ps is None:
            messages.error(request, _("Porespy is not installed on this server."))
            return redirect("pore_analysis_team:process_image", team_slug=team_slug)

        try:
            # Load original array
            with image.file.open("rb") as f:
                arr = np.load(f, allow_pickle=False).astype(bool)

            if arr.dtype != bool:
                messages.error(request, _("Selected image must be a boolean array."))
                return redirect("pore_analysis_team:process_image", team_slug=team_slug)

            # Run porespy operation
            processed = ps.filters.fill_invalid_pores(arr).astype(bool, copy=False)

            # Serialize .npy bytes
            buffer = BytesIO()
            np.save(buffer, processed, allow_pickle=False)
            file_bytes = buffer.getvalue()

            # Overwrite the same storage path
            storage = image.file.storage
            original_name = image.file.name
            storage.delete(original_name)
            storage.save(original_name, ContentFile(file_bytes))

            # Refresh model metadata
            image.file.name = original_name
            image.file_size = len(file_bytes)
            image.dimensions = list(processed.shape)

            # Regenerate thumbnail so UI reflects updated image
            if image.thumbnail:
                image.thumbnail.delete(save=False)
            image.generate_thumbnail(save=True)

            image.save()

            messages.success(request, _("Image processed successfully and overwritten."))
            return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=image.id)

        except Exception as exc:
            messages.error(request, _("Processing failed: {}").format(str(exc)))
            return redirect("pore_analysis_team:process_image", team_slug=team_slug)

    context = {
        "images": images,
        "team_slug": team_slug,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/process_image.html", context)
