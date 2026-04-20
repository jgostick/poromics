import openpnm as op
import streamlit as st
from funcs import render_network_and_image
import tempfile
import pathlib


state = st.session_state
for key, val in [
    ('network', None),
    ('pn', None),
    ('network_html', None),
    ('im_net_html', None),
]:
    if key not in state:
        state[key] = val


mu = 1.0
Dab = 1.0

for key, val in [('image_html', None)]:
    if key not in state:
        state[key] = val

if state['network'] is None:
    st.write('No network to validate yet')
else:
    pn = op.io.network_from_porespy(state['network'].network)

    h = op.utils.check_network_health(pn)
    for item in h.keys():
        if 'throat' in item:
            op.topotools.trim(pn, throats=h[item])
        if 'pore' in item:
            op.topotools.trim(pn, pores=h[item])
    vx = state['voxel_size']
    direction = st.selectbox('Direction', options=['x', 'y', 'z'])
    if direction == 'x':
        markers_in = [pn.coords[:, 0].min()*0.9, pn.coords[:, 1].mean(), pn.coords[:, 2].mean()]
        markers_out = [pn.coords[:, 0].max()*1.1, pn.coords[:, 1].mean(), pn.coords[:, 2].mean()]
        L = state['im'].shape[0] * vx
        A = state['im'].shape[2] * state['im'].shape[1] * vx**2
    elif direction == 'y':
        markers_in = [pn.coords[:, 0].mean(), pn.coords[:, 1].min()*0.9, pn.coords[:, 2].mean()]
        markers_out = [pn.coords[:, 0].mean(), pn.coords[:, 1].max()*1.1, pn.coords[:, 2].mean()]
        L = state['im'].shape[1] * vx
        A = state['im'].shape[2] * state['im'].shape[0] * vx**2
    elif direction == 'z':
        markers_in = [pn.coords[:, 0].mean(), pn.coords[:, 1].mean(), pn.coords[:, 2].min()*0.9]
        markers_out = [pn.coords[:, 0].mean(), pn.coords[:, 1].mean(), pn.coords[:, 2].max()*1.1]
        L = state['im'].shape[2] * vx
        A = state['im'].shape[0] * state['im'].shape[1] * vx**2

    op.topotools.find_surface_pores(
        network=pn,
        markers=markers_in,
        label='inlet',
    )
    op.topotools.find_surface_pores(
        network=pn,
        markers=markers_out,
        label='outlet',
    )

    with st.expander('Network properties'):
        st.code(str(pn))

    cols = st.columns(2)
    p_dia = cols[0].selectbox('Pore diameter', options=[i for i in pn.keys() if i.startswith('pore') and 'diameter' in i])
    t_dia = cols[1].selectbox('Throat diameter', options=[i for i in pn.keys() if i.startswith('throat') and 'diameter' in i])
    pn['pore.diameter'] = pn[p_dia]
    pn['throat.diameter'] = pn[t_dia]

    shape = st.selectbox(
        'Select Shape Model', 
        options=[i for i in dir(op.models.geometry.hydraulic_size_factors) if not i.startswith('_')],
        index=1,
    )
    pn.add_model(
        propname='throat.hydraulic_size_factors',
        model=getattr(op.models.geometry.hydraulic_size_factors, shape),
    )
    pn.add_model(
        propname='throat.diffusive_size_factors',
        model=getattr(op.models.geometry.diffusive_size_factors, shape),
    )
    phase = op.phase.Phase(network=pn)
    phase['pore.viscosity'] = mu
    phase['throat.viscosity'] = mu
    phase['pore.diffusivity'] = Dab
    phase['throat.diffusivity'] = Dab
    phase.add_model(
        propname='throat.hydraulic_conductance',
        model=op.models.physics.hydraulic_conductance.generic_hydraulic,
    )
    phase.add_model(
        propname='throat.diffusive_conductance',
        model=op.models.physics.diffusive_conductance.generic_diffusive,
    )

    sf = op.algorithms.StokesFlow(network=pn, phase=phase)
    sf.set_value_BC(pores=pn.pores('inlet'), values=1.0)
    sf.set_value_BC(pores=pn.pores('outlet'), values=0.0)
    sf.run()

    voxel_size = state.get('voxel_size', 1.0)
    Q = sf.rate(pores=pn.pores('inlet'))[0]
    K = Q * mu * L / A

    st.write(f"The permeability is: {K}")

    fd = op.algorithms.FickianDiffusion(network=pn, phase=phase)
    fd.set_value_BC(pores=pn.pores('inlet'), values=1.0)
    fd.set_value_BC(pores=pn.pores('outlet'), values=0.0)
    fd.run()

    N = fd.rate(pores=pn.pores('inlet'))[0]
    Deff = N * Dab * L / A

    st.write(f"The effective diffusivity is: {Deff}")
