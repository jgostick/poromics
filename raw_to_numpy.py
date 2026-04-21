file = st.file_uploader("Upload a .raw file", type=["raw"])
    if file is not None and file.file_id != state['raw_file_id']:
        if state['raw_tmp_path'] and os.path.exists(state['raw_tmp_path']):
            os.unlink(state['raw_tmp_path'])
        with tempfile.NamedTemporaryFile(suffix='.raw', delete=False) as tmp:
            tmp.write(file.read())
            state['raw_tmp_path'] = tmp.name
        state['raw_file_id'] = file.file_id
        state['raw_file_name'] = file.name
        file_size = os.path.getsize(state['raw_tmp_path'])
        state['raw_guess_dim'] = max(1, round(file_size ** (1/3)))
        st.success(f"Uploaded: {file.name}")

    if state['raw_tmp_path'] and os.path.exists(state['raw_tmp_path']):
        st.info(f"RAW ready: **{state['raw_file_name']}**")
        col1, col2, col3, col4 = st.columns(4)
        width = col1.number_input("Width (px)", value=state['raw_guess_dim'], min_value=1, step=1)
        height = col2.number_input("Height (px)", value=state['raw_guess_dim'], min_value=1, step=1)
        depth = col3.number_input("Depth (slices)", value=state['raw_guess_dim'], min_value=1, step=1)
        bit_depth = col4.selectbox("Bit depth / dtype", ["uint8", "uint16", "uint32", "float32", "float64"])
        if st.button('Convert to Array'):
            raw_bytes = open(state['raw_tmp_path'], 'rb').read()
            state['im'] = np.frombuffer(raw_bytes, dtype=np.dtype(bit_depth)).reshape((depth, height, width))
            st.success(f"Loaded array with shape {state['im'].shape} and dtype {state['im'].dtype}")