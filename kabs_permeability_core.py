"""Shared local kabs permeability execution logic.

This module is intentionally standalone so it can be imported both from the
main Django app and from the remote Taichi HTTP worker without relying on the
Django package layout.
"""


def compute_kabs_permeability_solution(*, image_array, direction, max_iterations, tolerance, backend, voxel_size):
    from kabs import compute_permeability, solve_flow

    soln = solve_flow(
        im=image_array,
        direction=direction,
        n_steps=max_iterations,
        tol=tolerance,
        verbose=False,
    )
    permeability = compute_permeability(
        soln=soln,
        direction=direction,
        dx_m=voxel_size,
    )

    return {
        "permeability [lu^2]": permeability["k_lu"],
        "direction": direction,
        "max_iterations": max_iterations,
        "tolerance": tolerance,
        "backend": backend,
        "voxel_size": voxel_size,
    }