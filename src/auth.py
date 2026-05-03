"""
OAuth 2.0 client credentials flow for the eBay Browse API.

Token is cached in cache/token.json and refreshed only when expired.
"""

import base64
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# Base URLs
PRODUCTION_BASE = "https://api.ebay.com"
SANDBOX_BASE = "https://api.sandbox.ebay.com"

TOKEN_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_PATH = Path(__file__).parent.parent / "cache" / "token.json"

# SSL workaround for this machine's broken cert store
REQUESTS_VERIFY = False


def _base_url(sandbox: bool = False) -> str:
    return SANDBOX_BASE if sandbox else PRODUCTION_BASE


def _load_cached_token() -> dict | None:
    """Return cached token dict if file exists and is not expired, else None."""
    if not TOKEN_PATH.exists():
        return None
    try:
        with TOKEN_PATH.open() as f:
            data = json.load(f)
        # Treat token as expired 60 seconds before actual expiry for safety margin
        if data.get("expires_at", 0) > time.time() + 60:
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _save_token(token_data: dict) -> None:
    """Persist token to disk with computed expires_at epoch."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    expires_at = time.time() + token_data.get("expires_in", 7200)
    record = {
        "access_token": token_data["access_token"],
        "token_type": token_data.get("token_type", "Application Access Token"),
        "expires_in": token_data.get("expires_in", 7200),
        "expires_at": expires_at,
    }
    with TOKEN_PATH.open("w") as f:
        json.dump(record, f, indent=2)


def _fetch_new_token(client_id: str, client_secret: str, sandbox: bool) -> dict:
    """Request a fresh Application Access Token from eBay."""
    base = _base_url(sandbox)
    url = f"{base}/identity/v1/oauth2/token"

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = f"grant_type=client_credentials&scope={TOKEN_SCOPE}"

    resp = requests.post(url, headers=headers, data=body, verify=REQUESTS_VERIFY, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_token(sandbox: bool = False, force_refresh: bool = False) -> str:
    """
    Return a valid eBay access token string.

    Loads credentials from environment (EBAY_CLIENT_ID, EBAY_CLIENT_SECRET).
    Uses cached token when possible; fetches a new one when expired or forced.

    Args:
        sandbox: Use eBay sandbox environment instead of production.
        force_refresh: Bypass cache and fetch a fresh token.

    Returns:
        Bearer token string.

    Raises:
        EnvironmentError: If credentials are not set.
        requests.HTTPError: If the token request fails.
    """
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise EnvironmentError(
            "EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set in your .env file.\n"
            "Copy .env.example to .env and fill in your eBay developer credentials.\n"
            "Get credentials at: https://developer.ebay.com"
        )

    if not force_refresh:
        cached = _load_cached_token()
        if cached:
            return cached["access_token"]

    token_data = _fetch_new_token(client_id, client_secret, sandbox)
    _save_token(token_data)
    return token_data["access_token"]


def get_auth_headers(sandbox: bool = False, force_refresh: bool = False) -> dict:
    """Return Authorization headers dict ready for requests."""
    token = get_token(sandbox=sandbox, force_refresh=force_refresh)
    return {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
