import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import numpy as np
from i18n import TRANSLATIONS, t, metric_keys
import os
import requests
from urllib.parse import urlencode

# Facebook Ads API imports
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative


# ========== Theming & Palette (Light/Dark aware) ==========
import plotly.express as px
from plotly.colors import sequential, diverging

def get_streamlit_theme_base() -> str:
    try:
        return (st.get_option("theme.base") or "light").lower()
    except Exception:
        return "light"


# ====== Facebook OAuth Config (keep secrets in env or Streamlit secrets) ======
def _cfg(key: str, default: str | None = None) -> str | None:
    # prefer Streamlit secrets, then env var; never hard-code secrets
    val = None
    try:
        val = st.secrets.get(key, None)
    except Exception:
        pass
    return val or os.getenv(key, default)

FB_APP_ID = _cfg("FB_APP_ID")              # None if not set
FB_APP_SECRET = _cfg("FB_APP_SECRET")      # None if not set
# IMPORTANT: Set this to the exact public URL of your Streamlit app page
# e.g. "https://your-domain.app/app" or when testing locally "http://localhost:8501"
FB_REDIRECT_URI = _cfg("FB_REDIRECT_URI", "http://localhost:8501/")
FB_SCOPES = ["ads_read"]  # add "business_management" if you need broader listing/asset mgmt

def style_fig(fig, *, height=400, showlegend=True):
    """Apply consistent background, grid, fonts, and sizing."""
    fig.update_layout(
        height=height,
        showlegend=showlegend,
        paper_bgcolor=PALETTE["bg"],
        plot_bgcolor=PALETTE["bg"],
        font=dict(color=PALETTE["text"]),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=60, b=10),
    )
    fig.update_xaxes(showgrid=True, gridcolor=PALETTE["grid"], zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=PALETTE["grid"], zeroline=False)
    return fig

# --- Secrets-based profiles ---
def load_secret_profiles():
    """
    Reads profiles from .streamlit/secrets.toml
    Expected shape:
    [profiles.<name>]
    APP_ID=""; APP_SECRET=""; ACCESS_TOKEN=""; AD_ACCOUNT_ID=""
    """
    profs = st.secrets.get("profiles", {})
    out = {}
    for name, vals in profs.items():
        out[name] = {
            "app_id": vals.get("APP_ID", ""),
            "app_secret": vals.get("APP_SECRET", ""),
            "access_token": vals.get("ACCESS_TOKEN", ""),
            "ad_account_id": vals.get("AD_ACCOUNT_ID", ""),
        }
    return out

def to_numeric(df, cols):
    """Convert specified columns to numeric"""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def derive_landing_page_views(df):
    """Derive landing page views from actions"""
    if 'actions' not in df.columns:
        df['landing_page_view'] = 0
        return df

    def pull(actions):
        total = 0.0
        try:
            arr = actions if isinstance(actions, list) else json.loads(actions)
            for a in arr or []:
                at = (a.get('action_type') or "")
                if at == 'landing_page_view':
                    v = a.get('value')
                    if v is not None:
                        try:
                            total += float(v)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass
        return total

    df['landing_page_view'] = df['actions'].apply(pull)
    return df
def derive_msg_starts(df):
    """Derive messaging_conversation_starts from actions"""
    if 'actions' not in df.columns:
        df['messaging_conversation_starts'] = 0
        return df

    def pull(actions):
        total = 0.0
        try:
            arr = actions if isinstance(actions, list) else json.loads(actions)
            for a in arr or []:
                at = (a.get('action_type') or "")
                if at.startswith('onsite_conversion.messaging_conversation_started'):
                    v = a.get('value')
                    if v is not None:
                        try:
                            total += float(v)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass
        return total

    df['messaging_conversation_starts'] = df['actions'].apply(pull)
    return df

def fetch_insights(ad_account_id, level, fields, start_date, end_date, 
                   time_increment=None, breakdowns=None):
    """Fetch insights from Facebook Ads API"""
    acct = AdAccount(ad_account_id)
    params = {
        'time_range': {'since': start_date, 'until': end_date},
        'level': level,
        'limit': 500,
        'action_report_time': 'conversion',
        'action_attribution_windows': ['7d_click', '1d_view'],
    }
    
    if time_increment:
        params['time_increment'] = time_increment
    if breakdowns:
        params['breakdowns'] = breakdowns

    data = list(acct.get_insights(fields=fields, params=params))
    return pd.DataFrame(data)

# ========== Data Fetching Functions ==========

@st.cache_data(ttl=3600)
def fetch_campaign_data(_api_init_params, ad_account_id, start_date, end_date):
    """Fetch campaign-level data"""
    fields = [
        AdsInsights.Field.campaign_name,
        AdsInsights.Field.spend,
        AdsInsights.Field.reach,
        AdsInsights.Field.impressions,
        AdsInsights.Field.clicks,
        AdsInsights.Field.ctr,
        AdsInsights.Field.cpc,
        "actions",
    ]
    
    df = fetch_insights(ad_account_id, "campaign", fields, start_date, end_date)
    df = derive_msg_starts(df)
    df = derive_landing_page_views(df)
    df = to_numeric(df, ["spend","reach","impressions","clicks","ctr","cpc","landing_page_view", "messaging_conversation_starts"])

    def calc_cpp(row):
        lpv = row.get("landing_page_view", 0)
        return (row["spend"] / lpv) if lpv not in (0, None) else None

    df["cost_per_lpv"] = df.apply(calc_cpp, axis=1)
    return df

@st.cache_data(ttl=3600)
def fetch_ad_data(_api_init_params, ad_account_id, start_date, end_date):
    fields = [
        AdsInsights.Field.ad_id,
        AdsInsights.Field.ad_name,
        AdsInsights.Field.adset_name,
        AdsInsights.Field.campaign_name,
        AdsInsights.Field.impressions,
        AdsInsights.Field.reach,          # <-- add
        AdsInsights.Field.clicks,
        AdsInsights.Field.ctr,
        AdsInsights.Field.cpc,
        AdsInsights.Field.spend,          # <-- add
        "actions",
    ]
    df = fetch_insights(ad_account_id, "ad", fields, start_date, end_date)
    df = derive_msg_starts(df)
    df = derive_landing_page_views(df)
    df = to_numeric(df, ["impressions","reach","clicks","ctr","cpc","spend",
                         "landing_page_view","messaging_conversation_starts"])
    # compute ad-level cost_per_lpv (optional but improves scoring)
    df["cost_per_lpv"] = np.where(
        (df["landing_page_view"] > 0),
        df["spend"] / df["landing_page_view"],
        np.nan
    )
    return df

@st.cache_data(ttl=3600)
def fetch_daily_data(_api_init_params, ad_account_id, start_date, end_date):
    fields = [AdsInsights.Field.date_start, AdsInsights.Field.clicks,
              AdsInsights.Field.impressions, "actions"]
    df = fetch_insights(ad_account_id, "account", fields, start_date, end_date, time_increment=1)
    df = derive_landing_page_views(df)
    df = derive_msg_starts(df)  # <-- add this
    df = to_numeric(df, ["clicks","impressions","landing_page_view","messaging_conversation_starts"])
    return df

@st.cache_data(ttl=3600)
def fetch_breakdown_data(_api_init_params, ad_account_id, start_date, end_date, breakdown_type):
    """Fetch data with specific breakdown"""
    fields = [AdsInsights.Field.clicks, AdsInsights.Field.impressions, "actions"]
    df = fetch_insights(ad_account_id, "account", fields, start_date, end_date, breakdowns=[breakdown_type])
    df = derive_landing_page_views(df)
    df = to_numeric(df, ["clicks","impressions","landing_page_view"])
    return df

@st.cache_data(ttl=3600)
def _best_preview_url_for_ad(ad_id: str) -> str | None:
    """
    Returns a preview image URL for a given ad:
    1) Try creative.thumbnail_url / image_url
    2) Fallback to Ad.get_previews() and parse the first <img src=...>
    """
    try:
        # 1) Try pulling creative thumbnail directly (fast & stable)
        creatives = Ad(ad_id).get_ad_creatives(
            fields=[
                AdCreative.Field.thumbnail_url,
                AdCreative.Field.image_url,
                AdCreative.Field.object_story_id,
            ],
            params={"limit": 1},
        )
        for c in creatives:
            url = c.get(AdCreative.Field.thumbnail_url) or c.get(AdCreative.Field.image_url)
            if url:
                return url
    except Exception:
        pass

    # 2) Fallback: generated preview HTML -> extract first <img src="...">
    try:
        previews = Ad(ad_id).get_previews(params={"ad_format": "DESKTOP_FEED_STANDARD"})
        for p in previews:
            html = p.get("body") or ""
            # tiny, permissive img-src extractor
            import re
            m = re.search(r'<img[^>]+src="([^"]+)"', html)
            if m:
                return m.group(1)
    except Exception:
        pass

    return None


import secrets

def fb_login_url() -> str:
    """Generate Facebook OAuth login URL - no state verification needed"""
    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": FB_REDIRECT_URI,  # Must match EXACTLY in token exchange
        "response_type": "code",
        "scope": ",".join(FB_SCOPES),
    }
    return f"https://www.facebook.com/v20.0/dialog/oauth?{urlencode(params)}"


def fb_exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for access token"""
    r = requests.get(
        "https://graph.facebook.com/v20.0/oauth/access_token",
        params={
            "client_id": FB_APP_ID,
            "redirect_uri": FB_REDIRECT_URI,  # MUST match the OAuth dialog request
            "client_secret": FB_APP_SECRET,
            "code": code,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def fb_long_lived_token(short_token: str) -> dict:
    """Exchange short-lived token for long-lived token (~60 days)"""
    r = requests.get(
        "https://graph.facebook.com/v20.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": FB_APP_ID,
            "client_secret": FB_APP_SECRET,
            "fb_exchange_token": short_token,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def fb_api_get(path: str, token: str, **params) -> dict:
    """Make authenticated request to Facebook Graph API"""
    r = requests.get(
        f"https://graph.facebook.com/v20.0/{path.lstrip('/')}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def main():
    st.set_page_config(
        page_title="Facebook Ads Dashboard",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # ---- Theme & Plotly defaults ----
    THEME_BASE = get_streamlit_theme_base()
    IS_DARK = THEME_BASE == "dark"

    global PALETTE, SERIES_COLOR_MAP
    PALETTE = {
        "text": "#e5e7eb" if IS_DARK else "#0f172a",
        "grid": "rgba(148, 163, 184, 0.25)" if IS_DARK else "rgba(100, 116, 139, 0.25)",
        "bg": "rgba(0,0,0,0)",
        "series": {
            "clicks":        "#3B82F6",
            "impressions":   "#F59E0B",
            "lpv":           "#22C55E",
            "conversations": "#A855F7",
            "spend":         "#EF4444",
            "reach":         "#06B6D4",
            "ctr":           "#10B981",
            "cpc":           "#F97316",
        },
        "categorical": [
            "#3B82F6","#22C55E","#F59E0B","#EF4444","#A855F7",
            "#06B6D4","#84CC16","#F97316","#EAB308","#10B981",
        ],
        "sequential": sequential.Viridis,
        "diverging":  diverging.RdBu,
    }

    px.defaults.template = "plotly_dark" if IS_DARK else "plotly"
    px.defaults.color_discrete_sequence = PALETTE["categorical"]
    px.defaults.color_continuous_scale = PALETTE["sequential"]

    SERIES_COLOR_MAP = {
        "Clicks":        PALETTE["series"]["clicks"],
        "Impressions":   PALETTE["series"]["impressions"],
        "Landing Page Views": PALETTE["series"]["lpv"],
        "Conversations": PALETTE["series"]["conversations"],
        "Spend":         PALETTE["series"]["spend"],
        "Reach":         PALETTE["series"]["reach"],
        "CTR":           PALETTE["series"]["ctr"],
        "CPC":           PALETTE["series"]["cpc"],
    }

    # Optional mapping for platform-specific colors (left empty to use default palette)
    platform_colors = {}

    # ====== OAuth Session State ======
    if "fb_user_token" not in st.session_state:
        st.session_state.fb_user_token = None
    if "fb_user_name" not in st.session_state:
        st.session_state.fb_user_name = None
    if "fb_ad_accounts" not in st.session_state:
        st.session_state.fb_ad_accounts = []

    # ====== Handle OAuth redirect ======
    qp = st.query_params
    code_param = qp.get("code")
    error_param = qp.get("error")

    if error_param:
        st.error(f"Facebook login error: {error_param}")
        error_desc = qp.get("error_description")
        if error_desc:
            st.error(f"Details: {error_desc}")
        st.stop()

    # Process the OAuth code if present
    if st.session_state.fb_user_token is None and code_param:
        try:
            with st.spinner("Completing sign-in..."):
                short = fb_exchange_code_for_token(code_param)
                longl = fb_long_lived_token(short["access_token"])
                st.session_state.fb_user_token = longl["access_token"]

                me = fb_api_get("/me", st.session_state.fb_user_token, fields="name,id")
                st.session_state.fb_user_name = me.get("name", "Facebook user")

                accs = fb_api_get(
                    "/me/adaccounts",
                    st.session_state.fb_user_token,
                    fields="id,account_id,name,currency,timezone_name",
                    limit=200,
                )
                st.session_state.fb_ad_accounts = accs.get("data", [])

                st.query_params.clear()
                st.success(f"✅ Signed in as {st.session_state.fb_user_name}")
                st.rerun()
                
        except requests.exceptions.HTTPError as e:
            st.error(f"❌ Facebook API error: {e}")
            try:
                error_detail = e.response.json()
                st.json(error_detail)
            except:
                st.code(e.response.text)
            st.stop()
        except Exception as e:
            st.error(f"❌ Login failed: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

    # ====== SIDEBAR: Authentication & Settings ======
    with st.sidebar:
        # If not logged in, show login options
        if not st.session_state.fb_user_token:
            # Optional logo above authentication header - try local file first, then LOGO_URL from config/secrets
            try:
                logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
            except Exception:
                logo_path = "logo.png"

            try:
                if os.path.exists(logo_path):
                    st.image(logo_path, width=100)
                else:
                    # prefer configured LOGO_URL, otherwise use this default URL
                    logo_url = _cfg("LOGO_URL", "")
                    if not logo_url:
                        logo_url = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRFVK7PWJ_oV1dYs3YBZJEN2sv0Xw-Gcf-grA&s"
                    if logo_url:
                        st.image(logo_url, width=100)
            except Exception:
                # Don't break the sidebar if image loading fails
                pass

            st.header("🔐 Authentication")
            
            # Try to load profiles
            try:
                profiles = load_secret_profiles()
            except Exception:
                profiles = {}
            
            # Show login method selector
            if profiles:
                login_method = st.radio(
                    "Choose login method:",
                    ["Facebook OAuth", "Saved Profile"],
                    label_visibility="collapsed"
                )
                
                if login_method == "Facebook OAuth":
                    st.markdown("### Sign in with Facebook")
                    st.info("Login to access all your ad accounts")
                    
                    # with st.expander("🔧 OAuth Debug Info"):
                    #     st.code(f"Redirect URI: {FB_REDIRECT_URI}")
                    #     st.caption("This must match your Facebook App settings")
                    
                    st.link_button(
                        "🔑 Sign in with Facebook", 
                        fb_login_url(), 
                        use_container_width=True,
                        type="primary"
                    )
                
                else:  # Saved Profile
                    st.markdown("### Use Saved Profile")
                    st.info("Quick access with pre-configured tokens")
                    
                    profile_names = list(profiles.keys())
                    selected_profile = st.selectbox(
                        "Select Profile", 
                        profile_names,
                        label_visibility="collapsed"
                    )
                    
                    if st.button("✓ Use This Profile", type="primary", use_container_width=True):
                        profile = profiles[selected_profile]
                        
                        if not profile.get("access_token") or not profile.get("ad_account_id"):
                            st.error("⚠️ Profile missing ACCESS_TOKEN or AD_ACCOUNT_ID")
                            st.stop()
                        
                        st.session_state.fb_user_token = profile["access_token"]
                        st.session_state.fb_user_name = f"Profile: {selected_profile}"
                        
                        # mark session as using a saved profile and persist the profile blob
                        st.session_state.is_profile_mode = True
                        st.session_state.selected_profile = {
                            "app_id": profile.get("app_id"),
                            "app_secret": profile.get("app_secret"),
                            "access_token": profile.get("access_token"),
                            "ad_account_id": profile.get("ad_account_id"),
                        }

                        # populate ad accounts in the same shape as OAuth path
                        st.session_state.fb_ad_accounts = [{
                            "id": profile["ad_account_id"],
                            "account_id": profile["ad_account_id"].replace("act_", ""),
                            "name": selected_profile,
                            "currency": "USD",
                            "timezone_name": "UTC"
                        }]
                        
                        st.success(f"✅ Loaded: {selected_profile}")
                        st.rerun()
                    
                    with st.expander("ℹ️ How to create profiles"):
                        st.markdown("""
                        **Send to Caden at: hoeyinf1@yahoo.com**
                        
                        ```toml
                        [profiles.my_account]
                        APP_ID = "your_app_id"
                        APP_SECRET = "your_app_secret"
                        ACCESS_TOKEN = "your_token"
                        AD_ACCOUNT_ID = "act_123456"
                        ```
                        
                        Get tokens at:
                        - [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
                        - [Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/)
                        """)
            
            else:
                # No profiles, show only OAuth
                st.markdown("### Sign in with Facebook")
                st.info("Login to access your ad accounts")
                
                with st.expander("🔧 OAuth Debug Info"):
                    st.code(f"Redirect URI: {FB_REDIRECT_URI}")
                    st.caption("This must match your Facebook App settings")
                
                st.link_button(
                    "🔑 Sign in with Facebook", 
                    fb_login_url(), 
                    use_container_width=True,
                    type="primary"
                )
                
                st.markdown("---")
                st.caption("💡 **Tip:** Add profiles to `secrets.toml` for quick access without OAuth")
            
            st.stop()
        
        # ====== If logged in, show account management ======
        st.header("⚙️ Settings")
        
        # Show current user
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"**{st.session_state.fb_user_name}**")
        with col2:
            if st.button("🚪", help="Logout", use_container_width=True):
                for k in ("fb_user_token", "fb_user_name", "fb_ad_accounts", "data_ready", "last_params"):
                    st.session_state.pop(k, None)
                st.query_params.clear()
                st.rerun()
        
        st.markdown("---")
        
        # Ad Account selection
        st.subheader("📊 Ad Account")
        acct_opts = []
        acct_id_map = {}
        for a in st.session_state.fb_ad_accounts:
            label = f"{a.get('name','(no name)')} — {a.get('account_id','?')} ({a.get('currency','')})"
            acct_opts.append(label)
            acct_id_map[label] = a.get("id")

        if not acct_opts:
            st.warning("No ad accounts available")
            st.stop()

        selected_label = st.selectbox("Select Account", acct_opts, index=0, label_visibility="collapsed")
        selected_ad_account_id = acct_id_map[selected_label]

        # Language selection
        st.markdown("---")
        lang = st.selectbox('🌐 Language', options=['en', 'zh'], index=0)
        
        # Translation helper
        def L_current(key):
            try:
                return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)
            except Exception:
                return key
        
        # Date range
        st.markdown("---")
        st.subheader("📅 " + L_current('date_range'))
        col1, col2 = st.columns(2)
        default_end = datetime.now().date()
        default_start = default_end - timedelta(days=30)
        with col1:
            start_date = st.date_input("Start", value=default_start, label_visibility="collapsed")
        with col2:
            end_date = st.date_input("End", value=default_end, label_visibility="collapsed")

        # Data loading
        if "data_ready" not in st.session_state:
            st.session_state.data_ready = False
        if "last_params" not in st.session_state:
            st.session_state.last_params = None

        load_clicked = st.button("📥 " + L_current('load_data'), type="primary", use_container_width=True)

        params_tuple = (selected_ad_account_id, str(start_date), str(end_date))
        if st.session_state.last_params != params_tuple:
            st.session_state.data_ready = False
            st.session_state.last_params = params_tuple
        if load_clicked:
            st.session_state.data_ready = True

        # Metric selection
        st.markdown("---")
        metric_keys_dict = metric_keys(lang)
        metric_options = list(metric_keys_dict.values())
        selected_metric = st.selectbox("📊 " + L_current('metric_select'), metric_options, index=0)
        metric_key = [k for k, v in metric_keys_dict.items() if v == selected_metric][0]
        
        # # Optional: Show token for creating profiles
        # st.markdown("---")
        # with st.expander("🔑 Access Token"):
        #     st.text_area(
        #         "Copy this for profiles (valid ~60 days)", 
        #         st.session_state.fb_user_token,
        #         height=80,
        #         label_visibility="collapsed"
        #     )
        #     st.caption("Use this token in `secrets.toml` for profile-based access")

    # Header
    st.markdown(
        f"""
        <div style="display: flex; align-items: center;">
            <img src="https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRFVK7PWJ_oV1dYs3YBZJEN2sv0Xw-Gcf-grA&s" width="100">
            <h1 style="display: inline-block; margin-left: 10px;">Facebook Ads Manager Dashboard</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")
    
    if not st.session_state.data_ready:
        st.info(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('select_profile_prompt'))
        
        with st.expander(L_current('getting_started'), expanded=True):
            st.markdown(f"""
            ### {L_current('getting_started_title')}
            
            1. **{L_current('getting_started_step1')}**: {L_current('getting_started_step1_details')}
            2. **{L_current('getting_started_step2')}**: {L_current('getting_started_step2_details')}
            3. **{L_current('getting_started_step3')}**: {L_current('getting_started_step3_details')}
            4. **{L_current('getting_started_step4')}**: {L_current('getting_started_step4_details')}
            
            ### {L_current('getting_started_creds_title')}
            - **{L_current('getting_started_creds_app')}**     [{L_current('WhatsApp')}](https://wa.link/k0zyxq)
            """)
        st.stop()
    
    
    # Initialize API using the logged-in user's token
    try:
        # Check if using saved profile or OAuth
        if st.session_state.get("is_profile_mode", False):
            # Use profile credentials
            profile = st.session_state.selected_profile
            FacebookAdsApi.init(
                profile["app_id"],
                profile["app_secret"],
                profile["access_token"]
            )
            api_params = (profile["app_id"], profile["app_secret"], profile["access_token"])
        else:
            # Use OAuth credentials
            FacebookAdsApi.init(
                FB_APP_ID,
                FB_APP_SECRET,
                st.session_state.fb_user_token
            )
            api_params = (FB_APP_ID, FB_APP_SECRET, st.session_state.fb_user_token)
        
    except Exception as e:
        st.error(f"❌ Failed to initialize Facebook Ads API: {str(e)}")
        st.stop()

    
    # Fetch Data
    with st.spinner(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('fetching_data')):
        try:
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")
            
            campaigns_df = fetch_campaign_data(api_params, selected_ad_account_id, start_str, end_str)
            ads_df = fetch_ad_data(api_params, selected_ad_account_id, start_str, end_str)
            # --- Build preview map keyed by ad_id ---
            preview_map = {}
            if 'ad_id' in ads_df.columns:
                unique_ids = [aid for aid in ads_df['ad_id'].dropna().unique().tolist() if str(aid)]
                # Be gentle with API: dedup + simple loop (cached by @st.cache_data)
                for aid in unique_ids:
                    url = _best_preview_url_for_ad(str(aid))
                    if url:
                        preview_map[str(aid)] = url

            daily_df = fetch_daily_data(api_params, selected_ad_account_id, start_str, end_str)
            # Ensure types and required columns for plotting
            if 'date_start' in daily_df.columns:
                daily_df['date_start'] = pd.to_datetime(daily_df['date_start'], errors='coerce')
            if 'messaging_conversation_starts' not in daily_df.columns:
                daily_df['messaging_conversation_starts'] = 0
            
            # Breakdowns
            gender_df = fetch_breakdown_data(api_params, selected_ad_account_id, start_str, end_str, "gender")
            age_df = fetch_breakdown_data(api_params, selected_ad_account_id, start_str, end_str, "age")
            device_df = fetch_breakdown_data(api_params, selected_ad_account_id, start_str, end_str, "impression_device")
            platform_df = fetch_breakdown_data(api_params, selected_ad_account_id, start_str, end_str, "publisher_platform")
            
        except Exception as e:
            st.error(f"❌ Error fetching data: {str(e)}")
            st.stop()
    
    st.success(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('data_loaded_success'))
    
    # ========== Key Metrics ==========
    st.header(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('key_metrics'))
    
    # Calculate totals
    total_spend = campaigns_df['spend'].sum() if 'spend' in campaigns_df.columns else 0
    total_clicks = campaigns_df['clicks'].sum() if 'clicks' in campaigns_df.columns else 0
    total_impressions = campaigns_df['impressions'].sum() if 'impressions' in campaigns_df.columns else 0
    total_reach = campaigns_df['reach'].sum() if 'reach' in campaigns_df.columns else 0
    total_landing_page_views = campaigns_df['landing_page_view'].sum() if 'landing_page_view' in campaigns_df.columns else 0
    avg_ctr = campaigns_df['ctr'].mean() if 'ctr' in campaigns_df.columns else 0
    avg_cpc = campaigns_df['cpc'].mean() if 'cpc' in campaigns_df.columns else 0
    
    total_messaging_conversation_starts = campaigns_df['messaging_conversation_starts'].sum() if 'messaging_conversation_starts' in campaigns_df.columns else 0
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('total_spend'),
            value=f"RM {total_spend:,.2f}",
            delta=None
        )
    
    with col2:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('total_clicks'),
            value=f"{total_clicks:,}",
            delta=None
        )
    
    with col3:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('landing_page_views'),
            value=f"{int(total_landing_page_views):,}",
            delta=None
        )
    
    with col4:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('total_reach'),
            value=f"{total_reach:,}",
            delta=None
        )
    
    col5, col6, col7, col8 = st.columns(4)
    
    with col5:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('total_conversations'),
            value=f"{int(total_messaging_conversation_starts):,}",
            delta=None
        )
    
    with col6:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('total_impressions'),
            value=f"{total_impressions:,}",
            delta=None
        )
    
    with col7:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('avg_ctr'),
            value=f"{avg_ctr:.2f}%",
            delta=None
        )
    
    with col8:
        st.metric(
            label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('avg_cpc'),
            value=f"RM {avg_cpc:.2f}",
            delta=None
        )
    
    # with col8:
    #     cost_per_lpv = (total_spend / total_landing_page_views) if total_landing_page_views > 0 else 0
    #     st.metric(
    #         label="🌐Cost/Landing Page View",
    #         value=f"RM {cost_per_lpv:.2f}",
    #         delta=None
    #     )
    
    st.markdown("---")
    
    # Helper function for ad scoring
    def score_ads(df):
        """Calculate composite performance score for ads with expanded metrics"""
        scores = pd.DataFrame()
        
        # Copy needed columns with safe defaults
        scores['ad_name'] = df['ad_name']
        scores['campaign_name'] = df['campaign_name']
        scores['clicks'] = df['clicks'].fillna(0)
        scores['impressions'] = df['impressions'].fillna(0)
        scores['landing_page_view'] = df['landing_page_view'].fillna(0) if 'landing_page_view' in df else pd.Series(0, index=df.index)
        scores['messaging_conversation_starts'] = df['messaging_conversation_starts'].fillna(0) if 'messaging_conversation_starts' in df else pd.Series(0, index=df.index)
        
        # Engagement Metrics
        scores['ctr'] = (100 * scores['clicks'] / scores['impressions']).replace([np.inf, -np.inf], 0).fillna(0)
        scores['lpv_rate'] = (100 * scores['landing_page_view'] / scores['clicks']).replace([np.inf, -np.inf], 0).fillna(0)
        scores['conv_rate'] = (100 * scores['messaging_conversation_starts'] / scores['clicks']).replace([np.inf, -np.inf], 0).fillna(0)
        
        # Efficiency Metrics
        scores['cost_per_click'] = (df['cpc'].fillna(0) if 'cpc' in df else pd.Series(0, index=df.index))
        scores['cost_per_lpv'] = (df['cost_per_lpv'].fillna(0) if 'cost_per_lpv' in df else pd.Series(0, index=df.index))
        
        # Volume & Reach Metrics
        scores['reach'] = df['reach'].fillna(0) if 'reach' in df else scores['impressions']
        scores['reach_rate'] = (100 * scores['reach'] / scores['impressions']).replace([np.inf, -np.inf], 0).fillna(0)
        
        # Frequency Score (penalize too high frequency)
        scores['frequency'] = (scores['impressions'] / scores['reach']).replace([np.inf, -np.inf], 0).fillna(0)
        scores['frequency_score'] = 1 - (scores['frequency'] / scores['frequency'].max() if scores['frequency'].max() > 0 else 0)
        scores['frequency_score'] = scores['frequency_score'].fillna(0)
        
        # Normalize metrics to 0-1 scale (inverse for cost metrics)
        positive_metrics = ['clicks', 'impressions', 'reach', 'ctr', 'lpv_rate', 'conv_rate', 'reach_rate']
        for col in positive_metrics:
            max_val = scores[col].max()
            if max_val > 0:
                scores[f'{col}_norm'] = scores[col] / max_val
            else:
                scores[f'{col}_norm'] = 0
        
        # Inverse normalization for cost metrics (lower is better)
        cost_metrics = ['cost_per_click', 'cost_per_lpv']
        for col in cost_metrics:
            max_val = scores[col].max()
            if max_val > 0:
                scores[f'{col}_norm'] = 1 - (scores[col] / max_val)
            else:
                scores[f'{col}_norm'] = 1  # Best score if no cost
        
        # Weighted Composite Score Components
        engagement_score = (
            scores['ctr_norm'] * 0.4 +
            scores['lpv_rate_norm'] * 0.3 +
            scores['conv_rate_norm'] * 0.3
        )
        
        efficiency_score = (
            scores['cost_per_click_norm'] * 0.5 +
            scores['cost_per_lpv_norm'] * 0.5
        )
        
        volume_score = (
            scores['clicks_norm'] * 0.4 +
            scores['reach_norm'] * 0.3 +
            scores['reach_rate_norm'] * 0.3
        )
        
        # Final composite score with component weights
        scores['composite_score'] = (
            engagement_score * 0.4 +      # Engagement quality
            efficiency_score * 0.3 +      # Cost efficiency
            volume_score * 0.2 +          # Volume & reach
            scores['frequency_score'] * 0.1  # Frequency optimization
        )
        
        # Scale to 0-100 for easier interpretation
        scores['composite_score'] = scores['composite_score'] * 100
        
        return scores
    
    # ========== Tabs for Different Views ==========
    tab_names = [
        L_current('tab_overview'),
        L_current('tab_campaigns'),
        L_current('tab_ads'),
        L_current('tab_demographics'),
        L_current('tab_devices'),
        L_current('winners_tab')
    ]
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(tab_names)
    
    # ========== Overview Tab ==========
    with tab1:
        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('daily_trends'))
        
        if not daily_df.empty:
            col1, col2 = st.columns(2)
            
            with col1:
                # Clicks & Impressions over time
                fig_daily = go.Figure()
                fig_daily.add_trace(go.Scatter(
                    x=daily_df['date_start'],
                    y=daily_df['clicks'],
                    mode='lines+markers',
                    name='Clicks',
                    line=dict(color=PALETTE["series"]["clicks"], width=3)
                ))
                fig_daily.add_trace(go.Scatter(
                    x=daily_df['date_start'],
                    y=daily_df['impressions'],
                    mode='lines+markers',
                    name='Impressions',
                    yaxis='y2',
                    line=dict(color=PALETTE["series"]["impressions"], width=3)
                ))
                fig_daily.update_layout(
                    title='Clicks & Impressions Over Time',
                    xaxis_title='Date',
                    yaxis_title='Clicks',
                    yaxis2=dict(title='Impressions', overlaying='y', side='right'),
                )
                style_fig(fig_daily, height=400)
                st.plotly_chart(fig_daily, use_container_width=True)
            
            with col2:
                # Metric over time
                if metric_key == "landing_page_views":
                    if 'landing_page_view' in daily_df.columns:
                        fig_conv = px.bar(
                            daily_df, x='date_start', y='landing_page_view',
                            title=L_current('lpv_by_day'),
                            labels={'date_start': L_current('date_label'), 'landing_page_view': L_current('lpv_label')}
                        )
                        fig_conv.update_traces(marker_color=PALETTE["series"]["lpv"])
                        style_fig(fig_conv, height=400)
                        st.plotly_chart(fig_conv, use_container_width=True)
                elif metric_key  == "total_conversations":
                    if 'messaging_conversation_starts' in daily_df.columns:
                        fig_msg = px.bar(
                            daily_df, x='date_start', y='messaging_conversation_starts',
                            title='Messaging Conversations Started by Day',
                            labels={'date_start': 'Date', 'messaging_conversation_starts': 'Conversations'}
                        )
                        fig_msg.update_traces(marker_color=PALETTE["series"]["conversations"])
                        style_fig(fig_msg, height=400)
                        st.plotly_chart(fig_msg, use_container_width=True)
        
        st.markdown("---")
        
        # Platform Distribution
        if not platform_df.empty and 'publisher_platform' in platform_df.columns:
            st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('performance_by_platform'))
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig_platform = px.pie(
                    platform_df,
                    values='clicks',
                    names='publisher_platform',
                    title='Clicks by Platform',
                    labels={'publisher_platform': 'Platform', 'clicks': 'Clicks'},
                    hole=0.7,
                    color='publisher_platform',
                    color_discrete_map=platform_colors
                )
                fig_platform.update_layout(height=400)
                st.plotly_chart(fig_platform, use_container_width=True)
            
            with col2:
                fig_platform_imp = px.pie(
                    platform_df,
                    values='impressions',
                    names='publisher_platform',
                    title='Impressions by Platform',
                    labels={'publisher_platform': 'Platform', 'impressions': 'Impressions'},
                    hole=0.7,
                    color='publisher_platform',
                    color_discrete_map=platform_colors
                )
                fig_platform_imp.update_layout(height=400)
                st.plotly_chart(fig_platform_imp, use_container_width=True)
        
        
    # ========== Campaigns Tab ==========
    with tab2:
        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('campaign_details'))
        
        if not campaigns_df.empty:
            # Display metrics
            display_df = campaigns_df[[
                'campaign_name', 'spend', 'reach', 'impressions', 'clicks',
                'landing_page_view', 'messaging_conversation_starts', 'cost_per_lpv', 'ctr', 'cpc'
            ]].copy()

            display_df.columns = [
                'Campaign', 'Spend (RM)', 'Reach', 'Impressions', 'Clicks',
                'Landing Page Views', 'Conversations', 'Cost/LPV (RM)', 'CTR (%)', 'CPC (RM)'
            ]

            # Format numbers
            for col in ['Spend (RM)', 'Cost/LPV (RM)', 'CPC (RM)', 'CTR (%)']:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")

            for col in ['Reach', 'Impressions', 'Clicks', 'Landing Page Views']:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")

            st.dataframe(display_df, use_container_width=True, height=400)
            
            # Visualizations
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            with col1:
                fig_spend = px.bar(
                    campaigns_df, x='campaign_name', y='spend',
                    title='Spend by Campaign',
                    labels={'campaign_name': 'Campaign', 'spend': 'Spend (RM)'}
                )
                fig_spend.update_traces(marker_color=PALETTE["series"]["spend"])
                style_fig(fig_spend, height=600)
                st.plotly_chart(fig_spend, use_container_width=True)
            
            with col2:
                if metric_key == "landing_page_views":
                    if 'landing_page_view' in campaigns_df.columns:
                        fig_conv = px.bar(
                            campaigns_df, x='campaign_name', y='landing_page_view',
                            title=L_current('lpv_by_campaign'),
                            labels={'campaign_name': 'Campaign', 'landing_page_view': 'Landing Page Views'}
                        )
                        fig_conv.update_traces(marker_color=PALETTE["series"]["lpv"])
                        style_fig(fig_conv, height=600)
                        st.plotly_chart(fig_conv, use_container_width=True)
                elif metric_key == "total_conversations":
                    if 'messaging_conversation_starts' in campaigns_df.columns:
                        fig_conv = px.bar(
                            campaigns_df, x='campaign_name', y='messaging_conversation_starts',
                            title='Conversations by Campaign',
                            labels={'campaign_name': 'Campaign', 'messaging_conversation_starts': 'Conversations'}
                        )
                        fig_conv.update_traces(marker_color=PALETTE["series"]["conversations"])
                        style_fig(fig_conv, height=600)
                        st.plotly_chart(fig_conv, use_container_width=True)

        else:
            st.warning("No campaign data available for the selected date range.")
    
    # ========== Ads Tab ==========
    with tab3:
        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('ads_details'))
        
        if not ads_df.empty:
            # Display metrics
            # --- Ads Tab table (robust, no length-mismatch) ---
            base_cols = [
                'ad_id', 'ad_name', 'adset_name', 'campaign_name', 'impressions',
                'clicks', 'landing_page_view', 'messaging_conversation_starts', 'ctr', 'cpc'
            ]
            available_cols = [c for c in base_cols if c in ads_df.columns]
            display_df = ads_df[available_cols].copy()

            # Map preview URL (built earlier as preview_map)
            if 'ad_id' in display_df.columns:
                display_df['Preview'] = display_df['ad_id'].astype(str).map(preview_map).fillna("")

            # Reorder so Preview is first; only keep those that exist
            desired_order = [
                'Preview', 'ad_name', 'adset_name', 'campaign_name',
                'impressions', 'clicks', 'landing_page_view',
                'messaging_conversation_starts', 'ctr', 'cpc'
            ]
            display_df = display_df[[c for c in desired_order if c in display_df.columns]]

            # Rename with a dict (no length mismatch)
            rename_map = {
                'ad_name': 'Ad Name',
                'adset_name': 'Ad Set',
                'campaign_name': 'Campaign',
                'impressions': 'Impressions',
                'clicks': 'Clicks',
                'landing_page_view': 'Landing Page Views',
                'messaging_conversation_starts': 'Conversations',
                'ctr': 'CTR (%)',
                'cpc': 'CPC (RM)',
            }
            display_df = display_df.rename(columns={k: v for k, v in rename_map.items() if k in display_df.columns})

            # Format numeric columns
            for col in ['Impressions', 'Clicks', 'Landing Page Views']:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
            for col in ['CTR (%)', 'CPC (RM)']:
                if col in display_df.columns:
                    display_df[col] = display_df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")

            # Show with image column
            st.dataframe(
                display_df,
                use_container_width=True,
                height=460,
                column_config={
                    "Preview": st.column_config.ImageColumn("Preview", help="Ad preview image", width="small")
                }
            )
            
            
            
            # Top performing ads
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('top_10_clicks'))
                top_clicks = ads_df.nlargest(10, 'clicks')[['ad_name', 'clicks']]
                fig_top_clicks = px.bar(
                    top_clicks, x='clicks', y='ad_name', orientation='h',
                    labels={'ad_name': 'Ad Name', 'clicks': 'Clicks'}
                )
                fig_top_clicks.update_traces(marker_color=PALETTE["series"]["clicks"])
                style_fig(fig_top_clicks, height=500, showlegend=False)
                st.plotly_chart(fig_top_clicks, use_container_width=True)
            
            with col2:
                if metric_key == "landing_page_views":
                    if 'landing_page_view' in ads_df.columns:
                        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('top_10_lpv'))
                        top_conv = ads_df.nlargest(10, 'landing_page_view')[['ad_name', 'landing_page_view']]
                        fig_top_conv = px.bar(
                            top_conv, x='landing_page_view', y='ad_name', orientation='h',
                            labels={'ad_name': 'Ad Name', 'landing_page_view': 'Landing Page Views'}
                        )
                        fig_top_conv.update_traces(marker_color=PALETTE["series"]["lpv"])
                        style_fig(fig_top_conv, height=500, showlegend=False)
                        st.plotly_chart(fig_top_conv, use_container_width=True)
                elif metric_key == "total_conversations":
                    if 'messaging_conversation_starts' in ads_df.columns:
                        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('top_10_conv'))
                        top_conv = ads_df.nlargest(10, 'messaging_conversation_starts')[['ad_name', 'messaging_conversation_starts']]
                        fig_top_conv = px.bar(
                            top_conv, x='messaging_conversation_starts', y='ad_name', orientation='h',
                            labels={'ad_name': 'Ad Name', 'messaging_conversation_starts': 'Conversations'}
                        )
                        fig_top_conv.update_traces(marker_color=PALETTE["series"]["conversations"])
                        style_fig(fig_top_conv, height=500, showlegend=False)
                        st.plotly_chart(fig_top_conv, use_container_width=True)
        else:
            st.warning(L_current('no_ads'))
    
    # ========== Demographics Tab ==========
    with tab4:
        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('audience_demographics'))
        
        col1, col2 = st.columns(2)
        
        with col1:
            if not age_df.empty and 'age' in age_df.columns:
                st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('age_distribution'))
                fig_age = px.bar(
                    age_df, x='age', y='clicks',
                    title='Clicks by Age Group',
                    labels={'age': 'Age Group', 'clicks': 'Clicks'}
                )
                fig_age.update_traces(marker_color=PALETTE["series"]["clicks"])
                style_fig(fig_age, height=400)
                st.plotly_chart(fig_age, use_container_width=True)
                
                # Data table
                age_display = age_df[['age', 'clicks', 'impressions']].copy()
                age_display.columns = ['Age Group', 'Clicks', 'Impressions']
                for col in ['Clicks', 'Impressions']:
                    age_display[col] = age_display[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
                st.dataframe(age_display, use_container_width=True)
        
        with col2:
            if not gender_df.empty and 'gender' in gender_df.columns:
                st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('gender_distribution'))
                fig_gender = px.pie(
                    gender_df, values='clicks', names='gender',
                    title='Clicks by Gender'
                )
                # Use default categorical sequence already set, or force first two:
                # fig_gender.update_traces(marker=dict(colors=PALETTE["categorical"][:len(gender_df["gender"].unique())]))
                style_fig(fig_gender, height=400)
                st.plotly_chart(fig_gender, use_container_width=True)
                
                # Data table
                gender_display = gender_df[['gender', 'clicks', 'impressions']].copy()
                gender_display.columns = ['Gender', 'Clicks', 'Impressions']
                for col in ['Clicks', 'Impressions']:
                    gender_display[col] = gender_display[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
                st.dataframe(gender_display, use_container_width=True)
        
    # ========== Devices & Platforms Tab ==========
    with tab5:
        st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('device_platform_analytics'))
        
        col1, col2 = st.columns(2)
        
        with col1:
            if not device_df.empty and 'impression_device' in device_df.columns:
                st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('device_breakdown'))
                fig_device = px.pie(
                    device_df, values='clicks', names='impression_device',
                    title='Clicks by Device'
                )
                style_fig(fig_device, height=400)
                st.plotly_chart(fig_device, use_container_width=True)
                
                # Data table
                device_display = device_df[['impression_device', 'clicks', 'impressions']].copy()
                device_display.columns = ['Device', 'Clicks', 'Impressions']
                for col in ['Clicks', 'Impressions']:
                    device_display[col] = device_display[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
                st.dataframe(device_display, use_container_width=True)
        
        with col2:
            if not platform_df.empty and 'publisher_platform' in platform_df.columns:
                st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('platform_performance'))
                
                # Calculate CTR for platforms
                # CTR with divide-by-zero guard
                platform_display = platform_df.copy()
                if 'impressions' in platform_display.columns and 'clicks' in platform_display.columns:
                    platform_display['ctr'] = (
                        (platform_display['clicks'] / platform_display['impressions'])
                        .replace([float('inf')], 0)
                        .fillna(0) * 100
                    ).round(2)

                # Long-form for stable colors by label
                _long = platform_display.melt(
                    id_vars=['publisher_platform'],
                    value_vars=['clicks', 'impressions'],
                    var_name='Metric',
                    value_name='Value'
                )
                # Pretty legend labels
                label_map = {'clicks': 'Clicks', 'impressions': 'Impressions'}
                _long['Metric'] = _long['Metric'].map(label_map)

                fig_platform_bar = px.bar(
                    _long,
                    x='publisher_platform',
                    y='Value',
                    color='Metric',
                    barmode='group',
                    title='Clicks vs Impressions by Platform',
                    labels={'publisher_platform': 'Platform', 'Value': 'Count', 'Metric': 'Metric'},
                    color_discrete_map={
                        'Clicks': SERIES_COLOR_MAP['Clicks'],
                        'Impressions': SERIES_COLOR_MAP['Impressions'],
                    },
                    category_orders={'Metric': ['Impressions', 'Clicks']}  # optional: fix legend/order
                )
                style_fig(fig_platform_bar, height=400)
                st.plotly_chart(fig_platform_bar, use_container_width=True)

                
                # Data table
                display_cols = ['publisher_platform', 'clicks', 'impressions']
                if 'ctr' in platform_display.columns:
                    display_cols.append('ctr')
                
                platform_table = platform_display[display_cols].copy()
                platform_table.columns = ['Platform', 'Clicks', 'Impressions', 'CTR (%)'][:len(display_cols)]
                
                for col in ['Clicks', 'Impressions']:
                    if col in platform_table.columns:
                        platform_table[col] = platform_table[col].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "0")
                if 'CTR (%)' in platform_table.columns:
                    platform_table['CTR (%)'] = platform_table['CTR (%)'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "0.00")
                
                st.dataframe(platform_table, use_container_width=True)

    # ========== Winners vs Underperformers Tab ==========
    with tab6:
        if not ads_df.empty:
            st.subheader(L_current('winners_tab'))

            # Calculate scores
            scores_df = score_ads(ads_df)

            # Filters
            col1, col2, col3 = st.columns(3)
            
            with col1:
                min_impressions = st.number_input(
                    L_current('min_impressions'),
                    min_value=0,
                    value=100,
                    step=100,
                    help="Filter out ads with fewer impressions"
                )
            
            with col2:
                min_clicks = st.number_input(
                    L_current('min_clicks'),
                    min_value=0,
                    value=10,
                    step=10,
                    help="Filter out ads with fewer clicks"
                )
            
            with col3:
                campaign_filter = st.multiselect(
                    L_current('filter_campaign'),
                    options=sorted(scores_df['campaign_name'].unique()),
                    help="Select specific campaigns to analyze"
                )

            # Apply filters
            mask = (
                (ads_df['impressions'] >= min_impressions) &
                (ads_df['clicks'] >= min_clicks)
            )
            if campaign_filter:
                mask &= scores_df['campaign_name'].isin(campaign_filter)

            filtered_scores = scores_df[mask].copy()

            if len(filtered_scores) > 0:
                # Split into winners and underperformers
                median_score = filtered_scores['composite_score'].median()
                winners = filtered_scores[filtered_scores['composite_score'] >= median_score].sort_values('composite_score', ascending=False)
                underperformers = filtered_scores[filtered_scores['composite_score'] < median_score].sort_values('composite_score')

                # Display results
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader(L_current('top_performers'))
                    metric_cols = [
                        'ad_name', 'campaign_name', 'composite_score',
                        'ctr', 'lpv_rate', 'conv_rate',
                        'cost_per_click', 'cost_per_lpv',
                        'reach_rate', 'frequency'
                    ]
                    winners_display = winners[metric_cols].copy()
                    winners_display.columns = [
                        'Ad Name', 'Campaign', 'Score',
                        'CTR %', 'LPV Rate %', 'Conv Rate %',
                        'CPC (RM)', 'Cost/LPV (RM)',
                        'Reach Rate %', 'Frequency'
                    ]
                    # Format numbers
                    percentage_cols = ['Score', 'CTR %', 'LPV Rate %', 'Conv Rate %', 'Reach Rate %']
                    cost_cols = ['CPC (RM)', 'Cost/LPV (RM)']
                    for col in percentage_cols:
                        winners_display[col] = winners_display[col].apply(lambda x: f"{x:.2f}")
                    for col in cost_cols:
                        winners_display[col] = winners_display[col].apply(lambda x: f"RM {x:.2f}")
                    winners_display['Frequency'] = winners_display['Frequency'].apply(lambda x: f"{x:.1f}x")
                    st.dataframe(winners_display, use_container_width=True, height=300)

                with col2:
                    st.subheader(L_current('needs_improve'))
                    underp_display = underperformers[metric_cols].copy()
                    underp_display.columns = winners_display.columns  # Use same column names
                    # Format numbers
                    for col in percentage_cols:
                        underp_display[col] = underp_display[col].apply(lambda x: f"{x:.2f}")
                    for col in cost_cols:
                        underp_display[col] = underp_display[col].apply(lambda x: f"RM {x:.2f}")
                    underp_display['Frequency'] = underp_display['Frequency'].apply(lambda x: f"{x:.1f}x")
                    st.dataframe(underp_display, use_container_width=True, height=300)

                # Performance Distribution Chart
                st.markdown("---")
                st.subheader(L_current('winners_tab') + ' - Performance Score Distribution')
                
                fig_scores = px.bar(
                    filtered_scores.sort_values('composite_score', ascending=False),
                    x='ad_name',
                    y='composite_score',
                    color='composite_score',
                    labels={'ad_name': 'Ad', 'composite_score': 'Performance Score'},
                    title='Ads Ranked by Performance Score',
                    color_continuous_scale='RdYlGn'  # Red to Yellow to Green scale
                )
                fig_scores.add_hline(
                    y=median_score,
                    line_dash="dash",
                    line_color="white",
                    annotation_text="Median Score"
                )
                style_fig(fig_scores, height=500)
                st.plotly_chart(fig_scores, use_container_width=True)

                # Explanation of scoring
                with st.expander(L_current('winners_tab') + ' - How Score is Calculated'):
                          st.markdown("""
                          The performance score (0-100) is calculated using four key components:
                    
                          1. Engagement Quality (40% of total score):
                              - Click-Through Rate (40%)
                              - Landing Page View Rate (30%)
                              - Conversation Rate (30%)
                    
                          2. Cost Efficiency (30% of total score):
                              - Cost per Click optimization (50%)
                              - Cost per Landing Page View optimization (50%)
                    
                          3. Volume & Reach (20% of total score):
                              - Click Volume (40%)
                              - Audience Reach (30%)
                              - Reach Rate (30%)
                    
                          4. Frequency Optimization (10% of total score):
                              - Optimal impression frequency score
                              - Penalizes excessive ad frequency
                    
                          Each component is normalized against the best performing ad in the filtered set.
                          The final score balances engagement, efficiency, scale, and frequency optimization.
                          Higher scores indicate better overall performance across these dimensions.
                          """)
            else:
                st.warning(L_current('no_match'))
        else:
            st.warning(L_current('no_ads'))
    
    # ========== Export Options ==========
    st.markdown("---")
    st.subheader(TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('export_data'))
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if not campaigns_df.empty:
            csv_campaigns = campaigns_df.to_csv(index=False)
            st.download_button(
                label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('download_campaign'),
                data=csv_campaigns,
                file_name=f"campaigns_{start_str}_{end_str}.csv",
                mime="text/csv"
            )
    
    with col2:
        if not ads_df.empty:
            csv_ads = ads_df.to_csv(index=False)
            st.download_button(
                label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('download_ads'),
                data=csv_ads,
                file_name=f"ads_{start_str}_{end_str}.csv",
                mime="text/csv"
            )
    
    with col3:
        if not daily_df.empty:
            csv_daily = daily_df.to_csv(index=False)
            st.download_button(
                label=TRANSLATIONS.get(lang, TRANSLATIONS['en']).get('download_daily'),
                data=csv_daily,
                file_name=f"daily_{start_str}_{end_str}.csv",
                mime="text/csv"
            )

if __name__ == "__main__":
    main()
