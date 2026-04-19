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
    from skimage.color import gray2rgb
    tmp = np.swapaxes(image_array, 0, axis)
    if np.ndim(image_array) > 2:  # noqa: SIM108
        thumb = tmp[int(tmp.shape[0]/2), ...]
    else:
        thumb = np.copy(image_array)
    thumb = gray2rgb(thumb)
    return thumb


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
