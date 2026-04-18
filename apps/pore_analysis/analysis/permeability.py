

def run_kabs_permeability(*, image_array, direction, max_iterations, tolerance, backend, voxel_size):

    from kabs import solve_flow, compute_permeability


    soln = solve_flow(
        im=image_array, 
        direction=direction,
        n_steps=max_iterations,
        tol=tolerance,
        verbose=False,
    )
    K = compute_permeability(
        soln=soln,
        direction=direction,
        dx_m=voxel_size,
    )

    solution = {
        "permeability [lu^2]": K['k_lu'],
        "direction": direction,
        "max_iterations": max_iterations,
        "tolerance": tolerance,
        "backend": backend,
        "voxel_size": voxel_size,
    }
    return solution
