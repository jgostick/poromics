import os
import tempfile

import numpy as np
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.pore_analysis.models import AnalysisType, UploadedImage
from apps.teams.decorators import login_and_team_required

from .utils import get_pore_analysis_context


@login_and_team_required 
def image_list(request, team_slug):
    """List all uploaded images for the team."""
    images = UploadedImage.objects.filter(team=request.team).order_by('-created_at')
    
    context = {
        'images': images,
    }
    
    # Add sidebar context
    context.update(get_pore_analysis_context(request))
    
    return render(request, 'pore_analysis/image_list.html', context)


@login_and_team_required
def refresh_image_metrics(request, team_slug):
    """Recompute metrics and regenerate missing thumbnails for team images."""
    if request.method != "POST":
        messages.error(request, _("Invalid request method."))
        return redirect("pore_analysis_team:image_list", team_slug=team_slug)

    images = UploadedImage.objects.filter(team=request.team).order_by("-created_at")
    metrics_refreshed_count = 0
    metrics_failed_count = 0
    thumbnails_regenerated_count = 0
    thumbnails_failed_count = 0

    for image in images:
        try:
            metrics = image.compute_metrics(save=True)
            if metrics:
                metrics_refreshed_count += 1
            else:
                metrics_failed_count += 1
        except Exception:
            metrics_failed_count += 1

        if not image.thumbnail:
            try:
                thumbnail_data = image.generate_thumbnail(save=True)
                if thumbnail_data:
                    image.save(update_fields=["thumbnail"])
                    thumbnails_regenerated_count += 1
                else:
                    thumbnails_failed_count += 1
            except Exception:
                thumbnails_failed_count += 1

    if metrics_refreshed_count:
        messages.success(
            request,
            _("Refreshed metrics for {} image(s).").format(metrics_refreshed_count),
        )

    if metrics_failed_count:
        messages.warning(
            request,
            _("Failed to refresh metrics for {} image(s).").format(metrics_failed_count),
        )

    if thumbnails_regenerated_count:
        messages.success(
            request,
            _("Regenerated missing thumbnails for {} image(s).").format(thumbnails_regenerated_count),
        )

    if thumbnails_failed_count:
        messages.warning(
            request,
            _("Failed to regenerate thumbnails for {} image(s).").format(thumbnails_failed_count),
        )

    if (
        not metrics_refreshed_count
        and not metrics_failed_count
        and not thumbnails_regenerated_count
        and not thumbnails_failed_count
    ):
        messages.info(request, _("No images found to refresh."))

    return redirect("pore_analysis_team:image_list", team_slug=team_slug)


@login_and_team_required
def image_detail(request, team_slug, image_id):
    """View details of a specific uploaded image."""
    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    analysis_jobs = image.analysis_jobs.all().order_by('-created_at')
    
    dims = image.dimensions
    max_x = dims[0]
    max_y = dims[1]
    max_z = dims[2] if len(dims) > 2 else 1

    context = {
        'image': image,
        'analysis_jobs': analysis_jobs,
        'analysis_types': AnalysisType.choices,
        'team_slug': team_slug,
        'orthoslice': {
            'max_x': max_x,
            'max_y': max_y,
            'max_z': max_z,
            'mid_x': max_x // 2,
            'mid_y': max_y // 2,
            'mid_z': max_z // 2,
            'is_3d': len(dims) == 3,
        },
    }
    context.update(get_pore_analysis_context(request))
    return render(request, 'pore_analysis/image_detail.html', context)


@login_and_team_required
def update_voxel_size(request, team_slug, image_id):
    """Update the voxel size of an uploaded image (HTMX endpoint)."""
    if request.method != "POST":
        return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=image_id)

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    raw = request.POST.get("voxel_size", "").strip()

    error = None
    if raw == "" or raw is None:
        image.voxel_size = None
        image.save(update_fields=["voxel_size", "updated_at"])
    else:
        try:
            value = float(raw)
            if value <= 0:
                error = _("Voxel size must be a positive number.")
            else:
                image.voxel_size = value
                image.save(update_fields=["voxel_size", "updated_at"])
        except ValueError:
            error = _("Enter a valid number.")

    context = {
        "image": image,
        "team_slug": team_slug,
        "voxel_size_error": error,
    }
    return render(request, "pore_analysis/components/voxel_size_field.html", context)


@login_and_team_required
def delete_image(request, team_slug, image_id):
    """Delete an uploaded image and its stored files."""
    if request.method != "POST":
        messages.error(request, _("Invalid request method."))
        return redirect("pore_analysis_team:image_list", team_slug=team_slug)

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    image_name = image.name

    try:
        # Remove stored files first (model delete does not always remove file blobs)
        if image.file:
            image.file.delete(save=False)
        if image.thumbnail:
            image.thumbnail.delete(save=False)

        image.delete()
        messages.success(request, _("Image '{}' was deleted.").format(image_name))
    except Exception as exc:
        messages.error(request, _("Could not delete image: {}").format(str(exc)))

    return redirect("pore_analysis_team:image_list", team_slug=team_slug)


@login_and_team_required
def upload_image(request, team_slug):
    """Upload a new volumetric image for analysis."""
    if request.method == 'POST':
        try:
            # Get form data
            uploaded_file = request.FILES.get('file')
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            voxel_size = request.POST.get('voxel_size', '').strip()

            # Validate required fields
            if not uploaded_file:
                return JsonResponse({'success': False, 'message': _('No file uploaded')})
            
            if not name:
                return JsonResponse({'success': False, 'message': _('Image name is required')})

            # Validate file type
            if not uploaded_file.name.lower().endswith('.npy'):
                return JsonResponse({'success': False, 'message': _('Only .npy files are supported')})

            # Validate file size (1GB limit)
            if uploaded_file.size > 1024 * 1024 * 1024:
                return JsonResponse({'success': False, 'message': _('File size must be less than 1GB')})

            # Process the numpy file to extract metadata
            try:
                # Save uploaded file to temporary location
                with tempfile.NamedTemporaryFile(delete=False, suffix='.npy') as temp_file:
                    for chunk in uploaded_file.chunks():
                        temp_file.write(chunk)
                    temp_file_path = temp_file.name

                # Load and validate numpy array
                try:
                    array = np.load(temp_file_path, allow_pickle=False).astype(bool)
                except Exception as e:
                    os.unlink(temp_file_path)  # Clean up temp file
                    return JsonResponse({'success': False, 'message': _('Invalid .npy file format')})
                
                # Validate array properties
                if array.dtype != bool:
                    os.unlink(temp_file_path)
                    return JsonResponse({'success': False, 'message': _('Array must be boolean type (True=pore, False=solid)')})
                
                # Get array dimensions
                dimensions = list(array.shape)
                
                # Validate dimensions (2D or 3D only)
                if len(dimensions) < 2 or len(dimensions) > 3:
                    os.unlink(temp_file_path)
                    return JsonResponse({'success': False, 'message': _('Array must be 2D or 3D')})

                # Clean up temp file
                os.unlink(temp_file_path)

            except Exception as e:
                return JsonResponse({'success': False, 'message': _('Error processing numpy file: {}').format(str(e))})

            # Parse voxel size
            voxel_size_value = None
            if voxel_size:
                try:
                    voxel_size_value = float(voxel_size)
                    if voxel_size_value <= 0:
                        return JsonResponse({'success': False, 'message': _('Voxel size must be positive')})
                except ValueError:
                    return JsonResponse({'success': False, 'message': _('Invalid voxel size')})

            # Create database record
            uploaded_image = UploadedImage.objects.create(
                team=request.team,
                uploaded_by=request.user,
                name=name,
                description=description,
                file=uploaded_file,
                file_size=uploaded_file.size,
                dimensions=dimensions,
                voxel_size=voxel_size_value,
            )
            
            # Ensure the file is saved before generating thumbnail
            uploaded_image.save()
            
            # Generate thumbnail using porespy
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"Attempting to generate thumbnail for {uploaded_image.name}")
                logger.info(f"File path: {uploaded_image.file.path}")
                logger.info(f"File exists: {os.path.exists(uploaded_image.file.path)}")
                
                thumbnail_data = uploaded_image.generate_thumbnail()
                if thumbnail_data:
                    uploaded_image.save()  # Save again to persist the thumbnail
                    logger.info(f"Thumbnail generation completed for {uploaded_image.name}")
                else:
                    logger.warning(f"Thumbnail generation returned None for {uploaded_image.name}")
                    
            except Exception as e:
                # Don't fail upload if thumbnail generation fails
                error_msg = f"Failed to generate thumbnail for {uploaded_image.name}: {type(e).__name__}: {e}"
                logger.error(error_msg, exc_info=True)
                print(error_msg)
                import traceback
                traceback.print_exc()

            # Compute metrics
            try:
                uploaded_image.compute_metrics(save=True)
            except Exception as e:
                logger.warning(f"Metrics computation failed for {uploaded_image.name}: {e}")

            # Return success response for AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': _('Image uploaded successfully!'),
                    'redirect_url': f'/a/{team_slug}/pore-analysis/images/{uploaded_image.id}/'
                })

            # Regular form submission
            messages.success(request, _('Image uploaded successfully!'))
            return redirect('pore_analysis_team:image_detail', team_slug=team_slug, image_id=uploaded_image.id)

        except Exception as e:
            error_message = _('Upload failed: {}').format(str(e))
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': error_message})
            
            messages.error(request, error_message)
            return render(request, 'pore_analysis/upload_image.html')

    # GET request - show upload form
    context = get_pore_analysis_context(request)
    return render(request, 'pore_analysis/upload_image.html', context)


def _render_orthoslice(request, image, x_idx, y_idx, z_idx, zoom_factor=1.2):
    """Render orthogonal slice planes in a 3D scene (server-side)."""
    import base64
    from io import BytesIO

    from PIL import Image
    import pyvista as pv

    # Memory-map for large files; fall back to regular load for cloud storage.
    try:
        arr = np.load(image.file.path, mmap_mode='r', allow_pickle=False)
    except (NotImplementedError, AttributeError):
        with image.file.open('rb') as f:
            arr = np.load(f, allow_pickle=False)

    is_2d = arr.ndim == 2

    if is_2d:
        data = np.asarray(arr, dtype=np.uint8)
        step = max(1, max(data.shape) // 512)
        data = data[::step, ::step]
        rgb = np.repeat((data * 255)[:, :, np.newaxis], 3, axis=2)
        image_array = rgb
        summary_text = _("2D slice preview")
        preview_caption = _("Orthoslice — 2D")
    else:
        max_x, max_y, max_z = arr.shape
        x_idx = max(0, min(int(x_idx), max_x - 1))
        y_idx = max(0, min(int(y_idx), max_y - 1))
        z_idx = max(0, min(int(z_idx), max_z - 1))
        zoom_factor = max(0.8, min(float(zoom_factor), 3.0))

        # Downsample large volumes before 3D rendering to keep response latency low.
        step = max(1, max(max_x, max_y, max_z) // 180)
        volume = np.asarray(arr[::step, ::step, ::step], dtype=np.uint8)

        x_small = max(0, min(x_idx // step, volume.shape[0] - 1))
        y_small = max(0, min(y_idx // step, volume.shape[1] - 1))
        z_small = max(0, min(z_idx // step, volume.shape[2] - 1))

        grid = pv.ImageData(dimensions=volume.shape)
        grid.point_data["InsideMesh"] = volume.ravel(order="F")
        slices = grid.slice_orthogonal(x=x_small, y=y_small, z=z_small)

        plotter = pv.Plotter(off_screen=True, window_size=(1400, 760))
        plotter.set_background("white")
        plotter.add_mesh(
            slices,
            scalars="InsideMesh",
            cmap="viridis",
            show_scalar_bar=False,
            lighting=False,
            clim=[0, 1],
        )
        plotter.camera_position = "iso"
        plotter.camera.zoom(zoom_factor)
        image_array = plotter.screenshot(return_img=True)
        plotter.close()

        summary_text = _("3D orthogonal slices — X={}, Y={}, Z={} (downsample step={}, zoom={:.1f}x)").format(
            x_idx,
            y_idx,
            z_idx,
            step,
            zoom_factor,
        )
        preview_caption = _("Orthoslice — X={}, Y={}, Z={}").format(x_idx, y_idx, z_idx)

    buffer = BytesIO()
    Image.fromarray(image_array).save(buffer, format="PNG")
    preview_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

    return render(
        request,
        "pore_analysis/components/tool_preview.html",
        {
            "preview_b64": preview_b64,
            "state": "original",
            "preview_caption": preview_caption,
            "badge_label": _("Preview"),
            "badge_class": "badge-info",
            "summary_text": summary_text,
            "preview_max_height_class": "max-h-[760px]",
            "show_save_controls": False,
        },
    )


@login_and_team_required
def orthoslice_preview(request, team_slug, image_id):
    """HTMX endpoint: returns a rendered orthoslice panel for the given image and indices."""
    if request.method != "POST":
        return redirect("pore_analysis_team:image_detail", team_slug=team_slug, image_id=image_id)

    image = get_object_or_404(UploadedImage, id=image_id, team=request.team)
    dims = image.dimensions
    max_x = dims[0]
    max_y = dims[1]
    max_z = dims[2] if len(dims) > 2 else 1

    x_idx = max(0, min(int(request.POST.get("x_idx", max_x // 2)), max_x - 1))
    y_idx = max(0, min(int(request.POST.get("y_idx", max_y // 2)), max_y - 1))
    z_idx = max(0, min(int(request.POST.get("z_idx", max_z // 2)), max_z - 1))
    try:
        zoom_factor = float(request.POST.get("zoom", "1.2"))
    except ValueError:
        zoom_factor = 1.2

    return _render_orthoslice(request, image, x_idx, y_idx, z_idx, zoom_factor=zoom_factor)
