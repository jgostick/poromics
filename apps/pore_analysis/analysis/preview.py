"""Utilities for generating in-browser image previews."""
import base64
from io import BytesIO

import numpy as np


def array_to_preview_png(arr: np.ndarray) -> str:
    """
    Return a base64-encoded PNG of the middle Z-slice (axis 2) of a 2D or 3D array.
    Suitable for embedding directly in HTML as: data:image/png;base64,<result>
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if arr.ndim == 3:
        mid = arr.shape[2] // 2
        slice_2d = arr[:, :, mid]
    elif arr.ndim == 2:
        slice_2d = arr
    else:
        raise ValueError(f"Expected a 2D or 3D array, got shape {arr.shape}")

    fig, ax = plt.subplots(figsize=(6, 6), dpi=100)

    if slice_2d.dtype.kind == "b":
        binary_cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
            "binary_phase",
            ["#111111", "#f4f4f4"],
        )
        ax.imshow(slice_2d.astype(np.uint8), cmap=binary_cmap, vmin=0, vmax=1, interpolation="nearest")
    else:
        ax.imshow(slice_2d, cmap="gray", interpolation="nearest")

    ax.axis("off")
    fig.tight_layout(pad=0)

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode("ascii")
