"""Reusable dashboard widgets for the Streamlit app."""

from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


TranslateFunc = Callable[[str], str]


def render_kpi_cards(
    campaigns_df: pd.DataFrame,
    metric_key: str,
    translate: TranslateFunc,
) -> None:
    """Render the headline KPI cards for the dashboard."""

    def series_aggregate(column: str, method: str) -> float:
        series = campaigns_df.get(column, pd.Series(dtype="float64"))
        series = pd.to_numeric(series, errors="coerce") if not series.empty else series
        if series.empty:
            return 0.0
        if method == "sum":
            return float(series.fillna(0).sum())
        filtered = series.replace([pd.NA, float("inf"), float("-inf")], pd.NA)
        filtered = filtered.dropna()
        if filtered.empty:
            return 0.0
        return float(filtered.mean())

    metric_definitions = {
        "spend": {
            "column": "spend",
            "aggregate": "sum",
            "label": translate("total_spend"),
            "formatter": lambda value: f"RM {value:,.2f}",
        },
        "clicks": {
            "column": "clicks",
            "aggregate": "sum",
            "label": translate("total_clicks"),
            "formatter": lambda value: f"{int(value):,}",
        },
        "landing_page_views": {
            "column": "landing_page_view",
            "aggregate": "sum",
            "label": translate("landing_page_views"),
            "formatter": lambda value: f"{int(value):,}",
        },
        "reach": {
            "column": "reach",
            "aggregate": "sum",
            "label": translate("total_reach"),
            "formatter": lambda value: f"{int(value):,}",
        },
        "total_conversations": {
            "column": "messaging_conversation_starts",
            "aggregate": "sum",
            "label": translate("total_conversations"),
            "formatter": lambda value: f"{int(value):,}",
        },
        "impressions": {
            "column": "impressions",
            "aggregate": "sum",
            "label": translate("total_impressions"),
            "formatter": lambda value: f"{int(value):,}",
        },
        "ctr": {
            "column": "ctr",
            "aggregate": "mean",
            "label": translate("avg_ctr"),
            "formatter": lambda value: f"{value:.2f}%",
        },
        "cpc": {
            "column": "cpc",
            "aggregate": "mean",
            "label": translate("avg_cpc"),
            "formatter": lambda value: f"RM {value:.2f}",
        },
    }

    display_order: Iterable[str] = (
        [metric_key] + [key for key in metric_definitions if key != metric_key]
        if metric_key in metric_definitions
        else list(metric_definitions.keys())
    )

    primary_badge = translate("primary_metric_badge")
    ordered_keys = list(display_order)
    for row_start in range(0, len(ordered_keys), 4):
        row_keys = ordered_keys[row_start : row_start + 4]
        if not row_keys:
            break
        cols = st.columns(len(row_keys))
        for column, key in zip(cols, row_keys):
            config = metric_definitions[key]
            raw_value = series_aggregate(config["column"], config["aggregate"])
            formatted_value = config["formatter"](raw_value if pd.notna(raw_value) else 0.0)
            label = config["label"]
            if key == metric_key and primary_badge:
                label = f"{label} ({primary_badge})"
            with column:
                st.metric(label=label, value=formatted_value)


def render_daily_trends(
    daily_df: pd.DataFrame,
    metric_key: str,
    translate: TranslateFunc,
    palette: dict,
    style_fig: Callable[..., None],
) -> None:
    """Render the dual-column daily trends charts."""

    if daily_df.empty:
        st.info(translate("no_daily_data"))
        return

    col1, col2 = st.columns(2)

    with col1:
        fig_daily = go.Figure()
        fig_daily.add_trace(
            go.Scatter(
                x=daily_df["date_start"],
                y=daily_df.get("clicks", pd.Series(dtype="float64")),
                mode="lines+markers",
                name="Clicks",
                line=dict(color=palette["series"]["clicks"], width=3),
            )
        )
        fig_daily.add_trace(
            go.Scatter(
                x=daily_df["date_start"],
                y=daily_df.get("impressions", pd.Series(dtype="float64")),
                mode="lines+markers",
                name="Impressions",
                yaxis="y2",
                line=dict(color=palette["series"]["impressions"], width=3),
            )
        )
        fig_daily.update_layout(
            title=translate("clicks_impressions_over_time"),
            xaxis_title=translate("date_label"),
            yaxis_title="Clicks",
            yaxis2=dict(title="Impressions", overlaying="y", side="right"),
        )
        style_fig(fig_daily, height=400)
        st.plotly_chart(fig_daily, use_container_width=True)

    with col2:
        metric_config = {
            "landing_page_views": {
                "column": "landing_page_view",
                "title": translate("lpv_by_day"),
                "label": translate("lpv_label"),
                "chart": "bar",
                "color": palette["series"].get("lpv"),
            },
            "total_conversations": {
                "column": "messaging_conversation_starts",
                "title": translate("conversations_by_day"),
                "label": translate("conversations_label"),
                "chart": "bar",
                "color": palette["series"].get("conversations"),
            },
            "spend": {
                "column": "spend",
                "title": translate("spend_by_day"),
                "label": translate("spend_label"),
                "chart": "bar",
                "color": palette["series"].get("spend"),
            },
            "clicks": {
                "column": "clicks",
                "title": translate("clicks_by_day"),
                "label": translate("clicks_label"),
                "chart": "line",
                "color": palette["series"].get("clicks"),
            },
            "impressions": {
                "column": "impressions",
                "title": translate("impressions_by_day"),
                "label": translate("impressions_label"),
                "chart": "line",
                "color": palette["series"].get("impressions"),
            },
            "reach": {
                "column": "reach",
                "title": translate("reach_by_day"),
                "label": translate("reach_label"),
                "chart": "line",
                "color": palette["series"].get("reach"),
            },
            "ctr": {
                "column": "ctr",
                "title": translate("ctr_by_day"),
                "label": translate("ctr_label"),
                "chart": "line",
                "color": palette["series"].get("ctr"),
            },
            "cpc": {
                "column": "cpc",
                "title": translate("cpc_by_day"),
                "label": translate("cpc_label"),
                "chart": "line",
                "color": palette["series"].get("cpc"),
            },
        }

        config = metric_config.get(metric_key)
        if not config or config["column"] not in daily_df.columns:
            st.info(translate("no_metric_daily_data"))
            return

        if config["chart"] == "line":
            fig_metric = px.line(
                daily_df,
                x="date_start",
                y=config["column"],
                title=config["title"],
                labels={
                    "date_start": translate("date_label"),
                    config["column"]: config["label"],
                },
            )
        else:
            fig_metric = px.bar(
                daily_df,
                x="date_start",
                y=config["column"],
                title=config["title"],
                labels={
                    "date_start": translate("date_label"),
                    config["column"]: config["label"],
                },
            )
        if config.get("color"):
            fig_metric.update_traces(marker_color=config["color"])
        style_fig(fig_metric, height=400)
        st.plotly_chart(fig_metric, use_container_width=True)


def render_platform_distribution(
    platform_df: pd.DataFrame,
    metric_key: str,
    translate: TranslateFunc,
    platform_colors: dict,
    palette: dict,
) -> None:
    """Render platform distribution donut charts."""

    if platform_df.empty or "publisher_platform" not in platform_df.columns:
        st.info(translate("no_platform_data"))
        return

    col1, col2 = st.columns(2)

    color_kwargs = (
        {"color_discrete_map": platform_colors}
        if platform_colors
        else {"color_discrete_sequence": palette.get("categorical")}
    )

    with col1:
        fig_platform = px.pie(
            platform_df,
            values="clicks",
            names="publisher_platform",
            title=translate("clicks_by_platform"),
            labels={"publisher_platform": translate("platform_label"), "clicks": translate("clicks_label")},
            hole=0.7,
            color="publisher_platform",
            **color_kwargs,
        )
        fig_platform.update_layout(height=400)
        st.plotly_chart(fig_platform, use_container_width=True)

    with col2:
        metric_config = {
            "landing_page_views": {
                "column": "landing_page_view",
                "title": translate("lpv_by_platform"),
                "label": translate("lpv_label"),
            },
            "total_conversations": {
                "column": "messaging_conversation_starts",
                "title": translate("conversations_by_platform"),
                "label": translate("conversations_label"),
            },
            "spend": {
                "column": "spend",
                "title": translate("spend_by_platform"),
                "label": translate("spend_label"),
            },
            "clicks": {
                "column": "clicks",
                "title": translate("clicks_by_platform"),
                "label": translate("clicks_label"),
            },
            "impressions": {
                "column": "impressions",
                "title": translate("impressions_by_platform"),
                "label": translate("impressions_label"),
            },
            "reach": {
                "column": "reach",
                "title": translate("reach_by_platform"),
                "label": translate("reach_label"),
            },
            "ctr": {
                "column": "ctr",
                "title": translate("ctr_by_platform"),
                "label": translate("ctr_label"),
            },
            "cpc": {
                "column": "cpc",
                "title": translate("cpc_by_platform"),
                "label": translate("cpc_label"),
            },
        }

        config = metric_config.get(metric_key) or metric_config.get("impressions")
        column_name = config["column"]
        if column_name not in platform_df.columns:
            st.info(translate("no_platform_data"))
            return

        fig_platform_metric = px.pie(
            platform_df,
            values=column_name,
            names="publisher_platform",
            title=config["title"],
            labels={"publisher_platform": translate("platform_label"), column_name: config["label"]},
            hole=0.7,
            color="publisher_platform",
            **color_kwargs,
        )
        fig_platform_metric.update_layout(height=400)
        st.plotly_chart(fig_platform_metric, use_container_width=True)
