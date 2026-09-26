# -*- coding: utf-8 -*-
"""Account-wide daily Workers AI usage from Cloudflare GraphQL analytics."""
from datetime import datetime, timezone
import math

import requests

from cloudflare_art_api import DEFAULT_MODEL, validate_settings


DAILY_NEURONS = 10000
QUERY = """
query($account: String!, $day: Date!) {
  viewer {
    accounts(filter: {accountTag: $account}) {
      aiInferenceAdaptiveGroups(limit: 1, filter: {date: $day}) {
        sum { totalNeurons }
      }
    }
  }
}
"""


class QuotaError(Exception):
    pass


def fetch_quota(account, token, *, session=None, now=None):
    if validate_settings(account, token, DEFAULT_MODEL):
        raise QuotaError("Квота ИИ: задайте Account ID и токен Cloudflare.")
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(timezone.utc).date().isoformat()
    http = session or requests
    try:
        response = http.post(
            "https://api.cloudflare.com/client/v4/graphql",
            headers={"Authorization": f"Bearer {token.strip()}"},
            json={"query": QUERY, "variables": {"account": account.strip(), "day": day}},
            timeout=(10, 20), allow_redirects=False)
        try:
            body = response.json()
            if response.status_code in (401, 403):
                raise QuotaError("Квота ИИ недоступна: проверьте токен и право Account Analytics: Read.")
            if response.status_code != 200 or not isinstance(body, dict):
                raise ValueError("invalid response")
            if body.get("errors"):
                auth = any(isinstance(e, dict) and (
                    (e.get("extensions") or {}).get("code") == "authz"
                    or "not authorized" in str(e.get("message", "")).lower())
                    for e in body["errors"])
                if auth:
                    raise QuotaError("Квота ИИ недоступна: добавьте токену Account Analytics: Read.")
                raise ValueError("analytics error")
            accounts = body["data"]["viewer"]["accounts"]
            if len(accounts) != 1:
                raise ValueError("account missing")
            rows = accounts[0]["aiInferenceAdaptiveGroups"]
            used = sum(float(row["sum"]["totalNeurons"]) for row in rows)
            if not math.isfinite(used) or used < 0:
                raise ValueError("invalid usage")
            return {"day": day, "used": used, "remaining": max(0, DAILY_NEURONS - used)}
        finally:
            response.close()
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise QuotaError("Квота ИИ временно недоступна. Повторите обновление.") from None
