import os
from typing import List

import streamlit.components.v1 as components

_COMPONENT_NAME = "dragdrop_board"
_COMPONENT_PATH = os.path.join(os.path.dirname(__file__), "frontend")

_dragdrop_component = components.declare_component(
    _COMPONENT_NAME,
    path=_COMPONENT_PATH,
)


def dragdrop_board(items: List[str], *, height: int = 320, key: str | None = None):
    """Render a drag-and-drop board and return the new order of items."""
    return _dragdrop_component(items=items, height=height, default=items, key=key)
