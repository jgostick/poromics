"""Scientific analysis functions for pore images."""
import numpy as np


def calculate_porosity(image_array):
    """
    Calculate porosity (fraction of pores) in the image.
    Assumes True = pore, False = solid.
    
    Returns float between 0 and 1.
    """
    if image_array.size == 0:
        return 0.0
    
    pore_count = np.sum(image_array > 0)
    total_count = image_array.size
    return float(pore_count / total_count)


def generate_thumbnail(image_array, axis=0):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tmp = np.swapaxes(image_array, 0, axis)
    if np.ndim(image_array) > 2:
        thumb = tmp[int(tmp.shape[0] / 2), ...]
    else:
        thumb = np.copy(image_array)

    # Normalise to [0, 1] so the colormap spans the full range
    thumb = thumb.astype(float)
    lo, hi = thumb.min(), thumb.max()
    if hi > lo:
        thumb = (thumb - lo) / (hi - lo)

    cmap = plt.get_cmap("turbo")
    rgb = cmap(thumb)[..., :3]  # drop alpha, keep RGB as float [0,1]
    return (rgb * 255).astype(np.uint8)


def get_image_metrics(image_array):
    """
    Calculate all available metrics for an image array.
    Returns dict of metric_name: value pairs.
    """
    min_value = np.amin(image_array).item()
    max_value = np.amax(image_array).item()

    return {
        "porosity": calculate_porosity(image_array),
        "shape": list(image_array.shape),
        "data_type": str(image_array.dtype),
        "range": [min_value, max_value],
        # Add more metrics here as you expand
        # 'permeability': calculate_permeability(image_array),
        # 'surface_area': calculate_surface_area(image_array),
    }
