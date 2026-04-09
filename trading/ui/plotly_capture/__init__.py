import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
_plotly_capture = components.declare_component("plotly_capture", path=_COMPONENT_DIR)


def plotly_chart_with_capture(figure, config=None, height=740, key=None):
    fig_dict = figure.to_dict() if hasattr(figure, "to_dict") else figure
    result = _plotly_capture(
        figure_data=fig_dict.get("data", []),
        figure_layout=fig_dict.get("layout", {}),
        config=config or {},
        height=height,
        key=key,
        default=None,
    )
    return result
