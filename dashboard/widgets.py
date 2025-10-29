"""Reusable dashboard widgets for the Streamlit app."""

from __future__ import annotations

from typing import Callable

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

    total_spend = campaigns_df.get("spend", pd.Series(dtype="float64")).sum()
    total_clicks = campaigns_df.get("clicks", pd.Series(dtype="float64")).sum()
    total_impressions = campaigns_df.get("impressions", pd.Series(dtype="float64")).sum()
    total_reach = campaigns_df.get("reach", pd.Series(dtype="float64")).sum()
    total_landing_page_views = campaigns_df.get("landing_page_view", pd.Series(dtype="float64")).sum()
    total_conversations = campaigns_df.get(
        "messaging_conversation_starts", pd.Series(dtype="float64")
    ).sum()
    avg_ctr = campaigns_df.get("ctr", pd.Series(dtype="float64")).mean()
    avg_cpc = campaigns_df.get("cpc", pd.Series(dtype="float64")).mean()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label=translate("total_spend"),
            value=f"RM {total_spend:,.2f}",
        )

    with col2:
        st.metric(
            label=translate("total_clicks"),
            value=f"{int(total_clicks):,}",
        )

    with col3:
        st.metric(
            label=translate("landing_page_views"),
            value=f"{int(total_landing_page_views):,}",
        )

    with col4:
        st.metric(
            label=translate("total_reach"),
            value=f"{int(total_reach):,}",
        )

    col5, col6, col7, col8 = st.columns(4)

    with col5:
        st.metric(
            label=translate("total_conversations"),
            value=f"{int(total_conversations):,}",
        )

    with col6:
        st.metric(
            label=translate("total_impressions"),
            value=f"{int(total_impressions):,}",
        )

    with col7:
        st.metric(
            label=translate("avg_ctr"),
            value=f"{(avg_ctr or 0):.2f}%",
        )

    with col8:
        st.metric(
            label=translate("avg_cpc"),
            value=f"RM {(avg_cpc or 0):.2f}",
        )


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
        if metric_key == "landing_page_views" and "landing_page_view" in daily_df.columns:
            fig_conv = px.bar(
                daily_df,
                x="date_start",
                y="landing_page_view",
                title=translate("lpv_by_day"),
                labels={
                    "date_start": translate("date_label"),
                    "landing_page_view": translate("lpv_label"),
                },
            )
            fig_conv.update_traces(marker_color=palette["series"]["lpv"])
            style_fig(fig_conv, height=400)
            st.plotly_chart(fig_conv, use_container_width=True)
        elif (
            metric_key == "total_conversations"
            and "messaging_conversation_starts" in daily_df.columns
        ):
            fig_msg = px.bar(
                daily_df,
                x="date_start",
                y="messaging_conversation_starts",
                title=translate("conversations_by_day"),
                labels={
                    "date_start": translate("date_label"),
                    "messaging_conversation_starts": translate("conversations_label"),
                },
            )
            fig_msg.update_traces(marker_color=palette["series"]["conversations"])
            style_fig(fig_msg, height=400)
            st.plotly_chart(fig_msg, use_container_width=True)
        else:
            st.info(translate("no_metric_daily_data"))


def render_platform_distribution(
    platform_df: pd.DataFrame,
    metric_key: str,
    translate: TranslateFunc,
    platform_colors: dict,
) -> None:
    """Render platform distribution donut charts."""

    if platform_df.empty or "publisher_platform" not in platform_df.columns:
        st.info(translate("no_platform_data"))
        return

    col1, col2 = st.columns(2)

    with col1:
        fig_platform = px.pie(
            platform_df,
            values="clicks",
            names="publisher_platform",
            title=translate("clicks_by_platform"),
            labels={"publisher_platform": translate("platform_label"), "clicks": translate("clicks_label")},
            hole=0.7,
            color="publisher_platform",
            color_discrete_map=platform_colors or None,
        )
        fig_platform.update_layout(height=400)
        st.plotly_chart(fig_platform, use_container_width=True)

    with col2:
        fig_platform_imp = px.pie(
            platform_df,
            values="impressions",
            names="publisher_platform",
            title=translate("impressions_by_platform"),
            labels={
                "publisher_platform": translate("platform_label"),
                "impressions": translate("impressions_label"),
            },
            hole=0.7,
            color="publisher_platform",
            color_discrete_map=platform_colors or None,
        )
        fig_platform_imp.update_layout(height=400)
        st.plotly_chart(fig_platform_imp, use_container_width=True)
