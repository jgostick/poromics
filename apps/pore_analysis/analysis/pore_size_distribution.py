

def run_poresize(image_array, sizes=25, voxel_size=1.0):
    import numpy as np
    import porespy as ps
    
    lt = ps.filters.local_thickness(
        im=image_array,
        method='dt',
        sizes=sizes,
        smooth=False,
    )
    psd = np.histogram(lt[image_array]*voxel_size, bins=sizes, density=True)
    return psd
