from typing import Any


def run_network_validation(
    net_dict: dict[str, Any],
    params: dict[str, Any],
    image_shape: list[int],
    voxel_size: float,
) -> dict[str, Any]:
    """
    Run OpenPNM StokesFlow and FickianDiffusion on a stored pore network.

    Returns a dict with permeability (K) and effective diffusivity (Deff)
    in the same dimensionless units used by the simulation (mu=1, Dab=1).
    Physical units depend on the voxel_size provided (metres).
    """
    import openpnm as op

    mu = 1.0
    Dab = 1.0

    direction = params.get("direction", "x")
    pore_diameter_key = params.get("pore_diameter_key", "pore.equivalent_diameter")
    throat_diameter_key = params.get("throat_diameter_key", "throat.equivalent_diameter")
    shape_model_name = params.get("shape_model", "balls_and_sticks")

    pn = op.io.network_from_porespy(net_dict)

    # Health check — trim problematic elements
    h = op.utils.check_network_health(pn)
    for item in h:
        if "throat" in item and len(h[item]):
            op.topotools.trim(pn, throats=h[item])
        if "pore" in item and len(h[item]):
            op.topotools.trim(pn, pores=h[item])

    vx = float(voxel_size)
    shape = [int(s) for s in image_shape]

    if direction == "x":
        markers_in = [pn.coords[:, 0].min() * 0.9, pn.coords[:, 1].mean(), pn.coords[:, 2].mean()]
        markers_out = [pn.coords[:, 0].max() * 1.1, pn.coords[:, 1].mean(), pn.coords[:, 2].mean()]
        L = shape[0] * vx
        A = shape[2] * shape[1] * vx**2 if len(shape) >= 3 else shape[1] * vx**2
    elif direction == "y":
        markers_in = [pn.coords[:, 0].mean(), pn.coords[:, 1].min() * 0.9, pn.coords[:, 2].mean()]
        markers_out = [pn.coords[:, 0].mean(), pn.coords[:, 1].max() * 1.1, pn.coords[:, 2].mean()]
        L = shape[1] * vx
        A = shape[2] * shape[0] * vx**2 if len(shape) >= 3 else shape[0] * vx**2
    else:  # z
        markers_in = [pn.coords[:, 0].mean(), pn.coords[:, 1].mean(), pn.coords[:, 2].min() * 0.9]
        markers_out = [pn.coords[:, 0].mean(), pn.coords[:, 1].mean(), pn.coords[:, 2].max() * 1.1]
        L = shape[2] * vx if len(shape) >= 3 else shape[1] * vx
        A = shape[0] * shape[1] * vx**2

    op.topotools.find_surface_pores(network=pn, markers=markers_in, label="inlet")
    op.topotools.find_surface_pores(network=pn, markers=markers_out, label="outlet")

    # Assign diameter fields
    if pore_diameter_key not in pn:
        available = [k for k in pn if k.startswith("pore") and "diameter" in k]
        if available:
            pore_diameter_key = available[0]
        else:
            raise ValueError(
                f"Pore diameter key '{pore_diameter_key}' not found in network. "
                f"Available pore keys: {[k for k in pn if k.startswith('pore')]}"
            )
    if throat_diameter_key not in pn:
        available = [k for k in pn if k.startswith("throat") and "diameter" in k]
        if available:
            throat_diameter_key = available[0]
        else:
            raise ValueError(
                f"Throat diameter key '{throat_diameter_key}' not found in network. "
                f"Available throat keys: {[k for k in pn if k.startswith('throat')]}"
            )

    pn["pore.diameter"] = pn[pore_diameter_key]
    pn["throat.diameter"] = pn[throat_diameter_key]

    # Geometry models
    shape_module_h = op.models.geometry.hydraulic_size_factors
    shape_module_d = op.models.geometry.diffusive_size_factors
    if not hasattr(shape_module_h, shape_model_name):
        raise ValueError(
            f"Shape model '{shape_model_name}' not found in openpnm.models.geometry.hydraulic_size_factors."
        )
    pn.add_model(
        propname="throat.hydraulic_size_factors",
        model=getattr(shape_module_h, shape_model_name),
    )
    pn.add_model(
        propname="throat.diffusive_size_factors",
        model=getattr(shape_module_d, shape_model_name),
    )

    # Phase
    phase = op.phase.Phase(network=pn)
    phase["pore.viscosity"] = mu
    phase["throat.viscosity"] = mu
    phase["pore.diffusivity"] = Dab
    phase["throat.diffusivity"] = Dab
    phase.add_model(
        propname="throat.hydraulic_conductance",
        model=op.models.physics.hydraulic_conductance.generic_hydraulic,
    )
    phase.add_model(
        propname="throat.diffusive_conductance",
        model=op.models.physics.diffusive_conductance.generic_diffusive,
    )

    # Stokes flow → permeability
    sf = op.algorithms.StokesFlow(network=pn, phase=phase)
    sf.set_value_BC(pores=pn.pores("inlet"), values=1.0)
    sf.set_value_BC(pores=pn.pores("outlet"), values=0.0)
    sf.run()

    Q = float(sf.rate(pores=pn.pores("inlet"))[0])
    K = Q * mu * L / A

    # Fickian diffusion → effective diffusivity
    fd = op.algorithms.FickianDiffusion(network=pn, phase=phase)
    fd.set_value_BC(pores=pn.pores("inlet"), values=1.0)
    fd.set_value_BC(pores=pn.pores("outlet"), values=0.0)
    fd.run()

    N = float(fd.rate(pores=pn.pores("inlet"))[0])
    Deff = N * Dab * L / A

    return {
        "permeability": float(K),
        "effective_diffusivity": float(Deff),
        "direction": direction,
        "pore_count": int(pn.Np),
        "throat_count": int(pn.Nt),
        "pore_diameter_key": pore_diameter_key,
        "throat_diameter_key": throat_diameter_key,
        "shape_model": shape_model_name,
    }
