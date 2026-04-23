import json
from io import BytesIO

import numpy as np
import porespy as ps
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _

from apps.pore_analysis.models import UploadedImage
from apps.teams.decorators import login_and_team_required

from .utils import get_pore_analysis_context


def _load_uploaded_image_array(image) -> np.ndarray:
    with image.file.open("rb") as f:
        return np.load(f, allow_pickle=False)


def _save_result_image(
    request,
    team_slug,
    image,
    result: np.ndarray,
    save_as: str,
    new_name: str,
    derived_suffix: str,
    derived_description: str,
    overwrite_message: str,
    new_message: str,
):
    buffer = BytesIO()
    np.save(buffer, result, allow_pickle=False)
    file_bytes = buffer.getvalue()

    if save_as == "overwrite":
        storage = image.file.storage
        original_name = image.file.name
        storage.delete(original_name)
        storage.save(original_name, ContentFile(file_bytes))
        image.file.name = original_name
        image.file_size = len(file_bytes)
        image.dimensions = list(result.shape)
        if image.thumbnail:
            image.thumbnail.delete(save=False)
        image.generate_thumbnail(save=True)
        image.compute_metrics(save=False)
        image.save()
        messages.success(request, overwrite_message)
        return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=image.id)

    name = new_name.strip() or f"{image.name}_{derived_suffix}"
    if not name.endswith(".npy"):
        name += ".npy"
    new_image = UploadedImage.objects.create(
        team=request.team,
        uploaded_by=request.user,
        name=name,
        description=derived_description.format(name=image.name),
        file=ContentFile(file_bytes, name=name),
        file_size=len(file_bytes),
        dimensions=list(result.shape),
        voxel_size=image.voxel_size,
    )
    new_image.generate_thumbnail(save=True)
    new_image.compute_metrics(save=False)
    new_image.save()
    messages.success(request, new_message.format(name=name))
    return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=new_image.id)


@login_and_team_required
def trim_image(request, team_slug):
    """Main trimming page using the shared tool shell."""
    if request.method == "POST" and request.POST.get("action") == "save":
        image_id = request.POST.get("image_id")
        image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
        arr = _load_uploaded_image_array(image)

        if arr.ndim == 2:
            max_x, max_y = arr.shape
            xmin = max(0, min(int(request.POST.get("xmin", 0)), max_x - 1))
            xmax = max(xmin + 1, min(int(request.POST.get("xmax", max_x)), max_x))
            ymin = max(0, min(int(request.POST.get("ymin", 0)), max_y - 1))
            ymax = max(ymin + 1, min(int(request.POST.get("ymax", max_y)), max_y))
            trimmed_array = arr[xmin:xmax, ymin:ymax]
        else:
            max_x, max_y, max_z = arr.shape
            xmin = max(0, min(int(request.POST.get("xmin", 0)), max_x - 1))
            xmax = max(xmin + 1, min(int(request.POST.get("xmax", max_x)), max_x))
            ymin = max(0, min(int(request.POST.get("ymin", 0)), max_y - 1))
            ymax = max(ymin + 1, min(int(request.POST.get("ymax", max_y)), max_y))
            zmin = max(0, min(int(request.POST.get("zmin", 0)), max_z - 1))
            zmax = max(zmin + 1, min(int(request.POST.get("zmax", max_z)), max_z))
            trimmed_array = arr[xmin:xmax, ymin:ymax, zmin:zmax]

        return _save_result_image(
            request=request,
            team_slug=team_slug,
            image=image,
            result=trimmed_array,
            save_as=request.POST.get("save_as", "new"),
            new_name=request.POST.get("new_name", ""),
            derived_suffix="trimmed",
            derived_description=_("Trimmed from {name}"),
            overwrite_message=_("Image trimmed successfully and overwritten."),
            new_message=_("New image '{name}' created."),
        )

    context = {
        "images": UploadedImage.objects.filter(team=request.team).order_by("-created_at"),
        "team_slug": team_slug,
        "load_image_url": reverse("pore_analysis_team:trim_image_load_image", kwargs={"team_slug": team_slug}),
        "preview_url": reverse("pore_analysis_team:trim_image_preview", kwargs={"team_slug": team_slug}),
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/trim_image.html", context)


def _render_trim_preview(request, image, xmin, xmax, ymin, ymax, zmin, zmax, show_save=False, save_url=""):
    """Render the trim overlay preview for the selected image and bounds."""
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    arr = _load_uploaded_image_array(image).astype(np.uint8)

    if arr.ndim == 2:
        arr = arr[:, :, np.newaxis]

    max_x, max_y, max_z = arr.shape

    xmin = max(0, min(int(xmin), max_x - 1))
    xmax = max(xmin + 1, min(int(xmax), max_x))
    ymin = max(0, min(int(ymin), max_y - 1))
    ymax = max(ymin + 1, min(int(ymax), max_y))
    zmin = max(0, min(int(zmin), max_z - 1))
    zmax = max(zmin + 1, min(int(zmax), max_z))

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

        # Keep binary phase rendering explicit: False/solid dark, True/void bright.
        unique_values = np.unique(z_data)
        is_binary = unique_values.size <= 2 and np.all(np.isin(unique_values, [0, 1]))
        colorscale = [[0.0, "#111111"], [1.0, "#f4f4f4"]] if is_binary else "Gray"

        fig.add_trace(
            go.Heatmap(
                z=z_data,
                x=x_vals,
                y=y_vals,
                colorscale=colorscale,
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

    trimmed_shape = (xmax - xmin, ymax - ymin, zmax - zmin)
    return render(
        request,
        "pore_analysis/components/tool_preview.html",
        {
            "plot_html": plot_html,
            "state": "processed" if show_save else "original",
            "preview_caption": _("Trim lines preview"),
            "badge_label": _("Trim"),
            "badge_class": "badge-info",
            "summary_text": _("Shape: {}" ).format(trimmed_shape),
            "show_save_controls": show_save,
            "save_url": save_url,
            "image_id": str(image.id),
            "hidden_inputs": [
                ("action", "save"),
                ("xmin", xmin),
                ("xmax", xmax),
                ("ymin", ymin),
                ("ymax", ymax),
                ("zmin", zmin),
                ("zmax", zmax),
            ],
            "suggested_name": image.name,
            "save_new_suffix": "trimmed",
        },
    )


@login_and_team_required
def trim_image_load_image(request, team_slug):
    """GET: load trim controls and initial preview for a selected image."""
    image_id = request.GET.get("image_id", "").strip()
    if not image_id:
        return HttpResponse("")

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    dimensions = list(image.dimensions)
    if len(dimensions) == 2:
        dimensions.append(1)

    preview_response = _render_trim_preview(
        request,
        image,
        0,
        dimensions[0],
        0,
        dimensions[1],
        0,
        dimensions[2],
    )
    controls_html = render_to_string(
        "pore_analysis/components/trim_controls.html",
        {
            "image": image,
            "dimensions": dimensions,
            "team_slug": team_slug,
            "preview_url": reverse("pore_analysis_team:trim_image_preview", kwargs={"team_slug": team_slug}),
        },
        request=request,
    )
    return HttpResponse(preview_response.content.decode("utf-8") + controls_html)


@login_and_team_required
def trim_image_preview(request, team_slug):
    """AJAX endpoint to preview trim bounds on original slices."""
    image_id = request.POST.get("image_id")
    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    show_save = request.POST.get("mode", "") == "applied"
    save_url = reverse("pore_analysis_team:trim_image", kwargs={"team_slug": team_slug})
    return _render_trim_preview(
        request,
        image,
        request.POST.get("xmin", 0),
        request.POST.get("xmax", image.dimensions[0]),
        request.POST.get("ymin", 0),
        request.POST.get("ymax", image.dimensions[1]),
        request.POST.get("zmin", 0),
        request.POST.get("zmax", image.dimensions[2] if len(image.dimensions) > 2 else 1),
        show_save=show_save,
        save_url=save_url,
    )


# ---------------------------------------------------------------------------
# Adjust Values – private helpers
# ---------------------------------------------------------------------------
def _apply_adjust_operation(arr: np.ndarray, operation: str, void_value: str = "") -> np.ndarray:
    """Apply an adjust-values operation and return the result array."""
    if operation == "invert":
        if arr.dtype.kind != "b":
            raise ValueError(_("Invert is only valid for boolean images."))
        return ~arr
    elif operation == "convert_to_bool":
        if void_value == "":
            raise ValueError(_("Please select a void value."))
        return arr == int(void_value)
    else:
        raise ValueError(_("Unknown operation: {}").format(operation))


def _save_adjusted_image(request, team_slug, image, result: np.ndarray, save_as: str, new_name: str):
    """Persist *result* either by overwriting *image* or creating a new record."""
    return _save_result_image(
        request=request,
        team_slug=team_slug,
        image=image,
        result=result,
        save_as=save_as,
        new_name=new_name,
        derived_suffix="adjusted",
        derived_description=_("Adjusted from {name}"),
        overwrite_message=_("Image updated successfully."),
        new_message=_("New image '{name}' created."),
    )


# ---------------------------------------------------------------------------
# Adjust Values – views
# ---------------------------------------------------------------------------
@login_and_team_required
def adjust_values(request, team_slug):
    """Main page: GET renders the tool shell; POST (action=save) persists the result."""
    if request.method == "POST" and request.POST.get("action") == "save":
        image_id = request.POST.get("image_id")
        image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
        try:
            with image.file.open("rb") as f:
                arr = np.load(f, allow_pickle=False)
            result = _apply_adjust_operation(
                arr,
                request.POST.get("operation", ""),
                request.POST.get("void_value", ""),
            )
        except (ValueError, Exception) as exc:
            messages.error(request, _("Save failed: {}").format(str(exc)))
            return redirect("pore_analysis_team:adjust_values", team_slug=team_slug)
        return _save_adjusted_image(
            request, team_slug, image, result,
            request.POST.get("save_as", "overwrite"),
            request.POST.get("new_name", ""),
        )

    images = UploadedImage.objects.filter(team=request.team).order_by("-created_at")
    save_url = reverse("pore_analysis_team:adjust_values", kwargs={"team_slug": team_slug})
    context = {
        "images": images,
        "team_slug": team_slug,
        "preview_url": reverse("pore_analysis_team:adjust_values_preview", kwargs={"team_slug": team_slug}),
        "load_image_url": reverse("pore_analysis_team:adjust_values_load_image", kwargs={"team_slug": team_slug}),
        "save_url": save_url,
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/adjust_values.html", context)


@login_and_team_required
def adjust_values_load_image(request, team_slug):
    """GET: load original slice preview + OOB operation controls for a selected image."""
    from apps.pore_analysis.analysis.preview import array_to_preview_png

    image_id = request.GET.get("image_id", "").strip()
    if not image_id:
        return HttpResponse("")

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    try:
        arr = _load_uploaded_image_array(image)
    except Exception as exc:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Could not load image: {}").format(exc)}</span></div>'
        )

    is_boolean = arr.dtype.kind == "b"
    unique_values = [] if is_boolean else sorted(int(v) for v in np.unique(arr).tolist())

    try:
        preview_b64 = array_to_preview_png(arr)
    except Exception as exc:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Preview failed: {}").format(exc)}</span></div>'
        )

    save_url = reverse("pore_analysis_team:adjust_values", kwargs={"team_slug": team_slug})

    preview_html = render_to_string(
        "pore_analysis/components/tool_preview.html",
        {"preview_b64": preview_b64, "state": "original", "save_url": save_url},
        request=request,
    )
    controls_html = render_to_string(
        "pore_analysis/components/adjust_values_controls.html",
        {"is_boolean": is_boolean, "unique_values": unique_values, "dtype": str(arr.dtype)},
        request=request,
    )
    return HttpResponse(preview_html + controls_html)


@login_and_team_required
def adjust_values_preview(request, team_slug):
    """POST: apply operation in memory, return processed preview with save buttons."""
    from apps.pore_analysis.analysis.preview import array_to_preview_png

    image_id = request.POST.get("image_id", "").strip()
    if not image_id:
        return HttpResponse(
            '<div class="alert alert-error"><span>No image selected.</span></div>'
        )

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    try:
        arr = _load_uploaded_image_array(image)
    except Exception as exc:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Could not load image: {}").format(exc)}</span></div>'
        )

    operation = request.POST.get("operation", "")
    void_value = request.POST.get("void_value", "")

    try:
        result = _apply_adjust_operation(arr, operation, void_value)
    except ValueError as exc:
        return render(
            request,
            "pore_analysis/components/tool_preview.html",
            {"error": str(exc), "state": "error"},
        )

    try:
        preview_b64 = array_to_preview_png(result)
    except Exception as exc:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Preview failed: {}").format(exc)}</span></div>'
        )

    save_url = reverse("pore_analysis_team:adjust_values", kwargs={"team_slug": team_slug})
    return render(
        request,
        "pore_analysis/components/tool_preview.html",
        {
            "preview_b64": preview_b64,
            "state": "processed",
            "save_url": save_url,
            "image_id": str(image_id),
            "hidden_inputs": [
                ("action", "save"),
                ("operation", operation),
                ("void_value", void_value),
            ],
            "suggested_name": image.name,
            "save_new_suffix": "adjusted",
        },
    )


PROCESS_IMAGE_SUPPORTED_OPERATIONS = {
    "fill_invalid_pores",
    "trim_floating_solid",
}


def _parse_process_operation_pipeline(raw_pipeline: str) -> list[str]:
    """Parse and validate the posted cleaning operation pipeline."""
    if not raw_pipeline:
        raise ValueError(_("Please apply at least one operation before saving."))

    try:
        operations = json.loads(raw_pipeline)
    except json.JSONDecodeError as exc:
        raise ValueError(_("Invalid operation pipeline.")) from exc

    if not isinstance(operations, list) or not operations:
        raise ValueError(_("Please apply at least one operation before saving."))

    normalized_operations = []
    for operation in operations:
        if not isinstance(operation, str):
            raise ValueError(_("Invalid operation pipeline."))
        op = operation.strip()
        if op not in PROCESS_IMAGE_SUPPORTED_OPERATIONS:
            raise ValueError(_("Unknown operation: {}").format(op))
        normalized_operations.append(op)

    return normalized_operations


def _apply_process_operation(arr: np.ndarray, operation: str) -> np.ndarray:
    """Apply a single cleaning operation to a boolean image array."""
    if arr.dtype.kind != "b":
        raise ValueError(_("Selected image must be a boolean array."))

    bool_arr = arr.astype(bool, copy=False)
    if operation == "fill_invalid_pores":
        result = ps.filters.fill_invalid_pores(bool_arr)
    elif operation == "trim_floating_solid":
        result = ps.filters.trim_floating_solid(bool_arr)
    else:
        raise ValueError(_("Unknown operation: {}").format(operation))

    return np.asarray(result).astype(bool, copy=False)


def _apply_process_operation_pipeline(arr: np.ndarray, operations: list[str]) -> np.ndarray:
    """Apply cleaning operations cumulatively in the provided order."""
    processed = arr
    for operation in operations:
        processed = _apply_process_operation(processed, operation)
    return processed


@login_and_team_required
def process_image(request, team_slug):
    """Main cleaning page: GET renders the tool shell; POST (action=save) persists the result."""
    if request.method == "POST" and request.POST.get("action") == "save":
        image_id = request.POST.get("image_id")
        image = get_object_or_404(UploadedImage, id=image_id, team=request.team)

        if ps is None:
            messages.error(request, _("Porespy is not installed on this server."))
            return redirect("pore_analysis_team:process_image", team_slug=team_slug)

        try:
            arr = _load_uploaded_image_array(image)
            operations = _parse_process_operation_pipeline(request.POST.get("operation_pipeline", "").strip())
            processed = _apply_process_operation_pipeline(arr, operations)
        except Exception as exc:
            messages.error(request, _("Processing failed: {}").format(str(exc)))
            return redirect("pore_analysis_team:process_image", team_slug=team_slug)

        return _save_result_image(
            request=request,
            team_slug=team_slug,
            image=image,
            result=processed,
            save_as=request.POST.get("save_as", "overwrite"),
            new_name=request.POST.get("new_name", ""),
            derived_suffix="cleaned",
            derived_description=_("Cleaned from {name}"),
            overwrite_message=_("Image processed successfully and overwritten."),
            new_message=_("New image '{name}' created."),
        )

    context = {
        "images": UploadedImage.objects.filter(team=request.team).order_by("-created_at"),
        "team_slug": team_slug,
        "preview_url": reverse("pore_analysis_team:process_image_preview", kwargs={"team_slug": team_slug}),
        "load_image_url": reverse("pore_analysis_team:process_image_load_image", kwargs={"team_slug": team_slug}),
    }
    context.update(get_pore_analysis_context(request))
    return render(request, "pore_analysis/process_image.html", context)


@login_and_team_required
def process_image_load_image(request, team_slug):
    """GET: load original slice preview for the cleaning tool."""
    from apps.pore_analysis.analysis.preview import array_to_preview_png

    image_id = request.GET.get("image_id", "").strip()
    if not image_id:
        return HttpResponse("")

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    try:
        arr = _load_uploaded_image_array(image)
        if arr.dtype.kind != "b":
            raise ValueError(_("Selected image must be a boolean array."))
        preview_b64 = array_to_preview_png(arr)
    except Exception as exc:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Could not prepare preview: {}").format(exc)}</span></div>'
        )

    preview_html = render_to_string(
        "pore_analysis/components/tool_preview.html",
        {"preview_b64": preview_b64, "state": "original"},
        request=request,
    )
    controls_html = render_to_string(
        "pore_analysis/components/process_image_controls.html",
        {
            "preview_url": reverse("pore_analysis_team:process_image_preview", kwargs={"team_slug": team_slug}),
        },
        request=request,
    )
    return HttpResponse(preview_html + controls_html)


@login_and_team_required
def process_image_preview(request, team_slug):
    """POST: apply cumulative cleaning operations and return a processed preview."""
    from apps.pore_analysis.analysis.preview import array_to_preview_png

    image_id = request.POST.get("image_id", "").strip()
    if not image_id:
        return HttpResponse('<div class="alert alert-error"><span>No image selected.</span></div>')

    if ps is None:
        return HttpResponse(
            f'<div class="alert alert-error"><span>{_("Porespy is not installed on this server.")}</span></div>'
        )

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    try:
        arr = _load_uploaded_image_array(image)
        operations = _parse_process_operation_pipeline(request.POST.get("operation_pipeline", "").strip())
        processed = _apply_process_operation_pipeline(arr, operations)
        preview_b64 = array_to_preview_png(processed)
    except Exception as exc:
        return render(
            request,
            "pore_analysis/components/tool_preview.html",
            {"error": _("Processing failed: {}").format(str(exc)), "state": "error"},
        )

    save_url = reverse("pore_analysis_team:process_image", kwargs={"team_slug": team_slug})
    return render(
        request,
        "pore_analysis/components/tool_preview.html",
        {
            "preview_b64": preview_b64,
            "state": "processed",
            "save_url": save_url,
            "image_id": str(image_id),
            "summary_text": _("Applied operations: {}").format(" -> ".join(operations)),
            "hidden_inputs": [
                ("action", "save"),
                ("operation_pipeline", json.dumps(operations)),
            ],
            "suggested_name": image.name,
            "save_new_suffix": "cleaned",
        },
    )
