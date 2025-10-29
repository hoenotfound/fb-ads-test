"""Utility helpers for handling dashboard sorting widgets."""

from __future__ import annotations

from typing import Iterable, List, Sequence

import pandas as pd
import streamlit as st

try:  # pragma: no cover - optional dependency
    from streamlit_sortable import sort_items as _native_sort_items
except ModuleNotFoundError:  # pragma: no cover - executed when optional dep missing
    _native_sort_items = None


__all__ = ["sort_items"]


def _fallback_sort_items(
    items: Sequence[str],
    *,
    key: str | None = None,
) -> List[str]:
    """Provide a graceful fallback when streamlit-sortable is unavailable.

    The fallback uses ``st.data_editor`` with an editable ``Order`` column so
    users can still control the placement of widgets without triggering an
    import error. The editor values are stably sorted to preserve edits while
    keeping duplicate order numbers predictable.
    """

    notice_key = f"sortable-missing-{key or 'default'}"
    if not st.session_state.get(notice_key):
        st.info(
            "Install the optional `streamlit-sortable` package to enable drag-and-"
            "drop reordering. Using number-based ordering as a fallback instead.",
        )
        st.session_state[notice_key] = True

    order_key = f"{key or 'sortable'}-fallback-order"
    if order_key not in st.session_state:
        st.session_state[order_key] = list(range(1, len(items) + 1))

    base_order = st.session_state[order_key]
    if len(base_order) != len(items):
        base_order = list(range(1, len(items) + 1))
        st.session_state[order_key] = base_order

    data = pd.DataFrame(
        {
            "Widget": list(items),
            "Order": base_order,
        }
    )

    edited = st.data_editor(
        data,
        use_container_width=True,
        hide_index=True,
        key=f"{order_key}-editor",
        column_config={
            "Widget": st.column_config.TextColumn("Widget", disabled=True),
            "Order": st.column_config.NumberColumn(
                "Order",
                min_value=1,
                max_value=len(items) if items else 1,
                step=1,
                help="Lower numbers appear first.",
            ),
        },
    )

    sorted_frame = edited.sort_values("Order", kind="stable").reset_index(drop=True)
    st.session_state[order_key] = sorted_frame["Order"].astype(int).tolist()
    return sorted_frame["Widget"].tolist()


def sort_items(
    items: Iterable[str],
    direction: str = "vertical",
    *,
    key: str | None = None,
    **kwargs,
) -> List[str]:
    """Wrapper around ``streamlit_sortable.sort_items`` with a resilient fallback."""

    normalized_items = list(items)
    if _native_sort_items:
        return list(_native_sort_items(normalized_items, direction=direction, key=key, **kwargs))
    return _fallback_sort_items(normalized_items, key=key)
