# Facebook Ads Dashboard

This repository contains a Streamlit dashboard for exploring Facebook Ads campaign performance. It layers the Facebook Marketing API on top of a friendly UI, adds language localisation, and enriches the data with helpful derived metrics such as landing-page views and conversation starts.

## Prerequisites

* Python **3.11+**
* A Facebook developer app with Marketing API access
* A long-lived access token for the account(s) you want to inspect

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

The dashboard expects the following secrets:

| Key | Description |
| --- | --- |
| `FB_APP_ID` | Facebook App ID used for OAuth. |
| `FB_APP_SECRET` | Facebook App Secret used to exchange tokens. |
| `FB_REDIRECT_URI` | Exact redirect URL registered in your Facebook app settings. |

Provide them either through Streamlit secrets (`.streamlit/secrets.toml`) or environment variables. Example `secrets.toml`:

```toml
[profiles.my_account]
APP_ID = "123"
APP_SECRET = "abc"
ACCESS_TOKEN = "EAAB..."
AD_ACCOUNT_ID = "act_123"
```

## Running Locally

```bash
streamlit run app.py
```

Visit http://localhost:8501 after the server boots.

## Troubleshooting

* Make sure the configured redirect URI matches the URL that Streamlit is serving, otherwise Facebook will reject the OAuth flow.
* The first call to the API may take a few seconds as Streamlit populates its caches. Subsequent requests are cached for one hour.
* If you change any credentials in `secrets.toml`, restart the Streamlit process to reload them.

## Applying the Latest Changes

If you are picking up the updates introduced in the most recent commits and already have a local clone of this repository, run the
following commands from the project root:

```bash
git pull origin work   # or the branch name that contains the new changes
pip install -r requirements.txt
streamlit run app.py
```

The `git pull` brings your local checkout up to date, the `pip install` step ensures any new dependencies are installed, and the
final command launches the refreshed dashboard so you can immediately verify the formatting and data handling improvements.
