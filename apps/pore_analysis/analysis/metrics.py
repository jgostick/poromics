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
    
    pore_count = np.sum(image_array)
    total_count = image_array.size
    return float(pore_count / total_count)


def get_image_metrics(image_array):
    """
    Calculate all available metrics for an image array.
    Returns dict of metric_name: value pairs.
    """
    return {
        'porosity': calculate_porosity(image_array),
        'shape': image_array.shape
        # Add more metrics here as you expand
        # 'permeability': calculate_permeability(image_array),
        # 'surface_area': calculate_surface_area(image_array),
    }