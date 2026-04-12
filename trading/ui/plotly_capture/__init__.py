import json
import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_plotly_capture = components.declare_component("plotly_capture", path=_COMPONENT_DIR)


def _make_serializable(obj):
    """Recursively convert numpy/non-JSON-serializable types to native Python."""
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
    except ImportError:
        pass
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    return obj


def plotly_chart_with_capture(figure, config=None, height=740, key=None):
    fig_dict = figure.to_dict() if hasattr(figure, "to_dict") else figure
    fig_dict = _make_serializable(fig_dict)
    result = _plotly_capture(
        figure_data=fig_dict.get("data", []),
        figure_layout=fig_dict.get("layout", {}),
        config=config or {},
        height=height,
        key=key,
        default=None,
    )
    return result
