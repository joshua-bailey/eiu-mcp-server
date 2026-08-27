"""EIU (Economist Intelligence Unit) MCP Server v0.1.

Token-efficient tools for discovering and fetching forecast data from the
EIU API. Provides browse, search, and data retrieval for ~200 countries
and ~320 economic indicator series.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("eiu")

# EIU API base URL
BASE_URL = "https://api.eiu.com/v1"

# Cached reference data (loaded once, reused by browse/search)
_REF_DATA: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compact(obj) -> str:
    """Compact JSON serialisation — no whitespace."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text to max_len chars, appending '...' if needed."""
    if not text or len(text) <= max_len:
        return (text or "").strip()
    return text[: max_len - 3].strip() + "..."


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

class EIUTokenManager:
    """Manages EIU API bearer token lifecycle.

    Obtains token via POST /login on first request, caches in memory,
    refreshes proactively when within 5 minutes of expiry.
    """

    def __init__(self, api_key: str, email: str, password: str):
        self._api_key = api_key
        self._email = email
        self._password = password
        self._token: str | None = None
        self._expires_at: float = 0

    def headers(self) -> dict:
        """Return complete auth headers, auto-logging in if needed."""
        if self._token is None or time.time() > self._expires_at - 300:
            self._login()
        return {
            "x-api-key": self._api_key,
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _login(self):
        # EIU login requires string body (data=), not json object (json=)
        resp = requests.post(
            f"{BASE_URL}/login",
            data=json.dumps({"emailAddress": self._email, "password": self._password}),
            headers={"x-api-key": self._api_key, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["token"]
        self._expires_at = time.time() + data.get("expiresIn", 3600)

    def invalidate(self):
        """Force re-login on next request."""
        self._token = None
        self._expires_at = 0


# Lazy singleton
_TOKEN_MGR: EIUTokenManager | None = None


def _get_mgr() -> EIUTokenManager:
    """Get or create the token manager from environment variables."""
    global _TOKEN_MGR
    if _TOKEN_MGR is None:
        api_key = os.environ.get("EIU_API_KEY")
        email = os.environ.get("EIU_EMAIL")
        password = os.environ.get("EIU_PASSWORD")
        if not all([api_key, email, password]):
            raise ValueError(
                "EIU credentials not set. "
                "Set EIU_API_KEY, EIU_EMAIL, and EIU_PASSWORD environment variables."
            )
        _TOKEN_MGR = EIUTokenManager(api_key, email, password)
    return _TOKEN_MGR


def _api_get(path: str, params: dict | None = None, timeout: int = 30):
    """GET request with auth and retry-on-401."""
    mgr = _get_mgr()
    resp = requests.get(
        f"{BASE_URL}{path}",
        params=params,
        headers=mgr.headers(),
        timeout=timeout,
    )
    if resp.status_code == 401:
        mgr.invalidate()
        resp = requests.get(
            f"{BASE_URL}{path}",
            params=params,
            headers=mgr.headers(),
            timeout=timeout,
        )
    resp.raise_for_status()
    return resp.json()


def _api_post(path: str, body: dict, timeout: int = 30):
    """POST request with auth and retry-on-401."""
    mgr = _get_mgr()
    resp = requests.post(
        f"{BASE_URL}{path}",
        json=body,
        headers=mgr.headers(),
        timeout=timeout,
    )
    if resp.status_code == 401:
        mgr.invalidate()
        resp = requests.post(
            f"{BASE_URL}{path}",
            json=body,
            headers=mgr.headers(),
            timeout=timeout,
        )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Reference data caching
# ---------------------------------------------------------------------------

def _load_ref_data() -> dict:
    """Load and cache reference data (geographies + series tree)."""
    global _REF_DATA
    if _REF_DATA is not None:
        return _REF_DATA

    raw = _api_get("/data/referencedata", timeout=60)
    dp = raw.get("dataPackage", raw)

    # Flatten geographies from dataPackage.geographyLocations
    geos = []
    for region in dp.get("geographyLocations", []):
        for country in region.get("children", []):
            code = country.get("code", "")
            if code:
                geos.append({"c": code, "n": country.get("name", "")})

    # Flatten series from dataPackage.series (nested categories)
    series = []
    _flatten_series(dp.get("series", []), series, category="")

    _REF_DATA = {"geographies": geos, "series": series}
    return _REF_DATA


def _flatten_series(nodes: list, out: list, category: str):
    """Recursively flatten series tree into list of {code, name, cat}."""
    for node in nodes:
        code = node.get("code", "")
        name = node.get("name", "")
        children = node.get("children", [])
        if code and node.get("id") is not None:
            # Leaf node: actual series
            out.append({"c": code, "n": _truncate(name, 60), "cat": category})
        if children:
            # Category node: recurse with this node's name as category
            _flatten_series(children, out, name if not code else category)


# ---------------------------------------------------------------------------
# Tool 1: eiu_browse
# ---------------------------------------------------------------------------

@mcp.tool()
def eiu_browse(filter: str = "", show: str = "both") -> str:
    """Browse available EIU geographies and data series.

    Call with no filter to see all available geographies/series.
    Use filter to narrow results by keyword.

    Args:
        filter: Optional keyword (e.g. 'Brazil', 'GDP', 'inflation')
        show: 'geographies', 'series', or 'both' (default)
    """
    try:
        ref = _load_ref_data()
    except Exception as e:
        return _compact({"error": str(e)})

    filt = filter.lower().strip()
    result = {}

    if show in ("both", "geographies"):
        geos = ref["geographies"]
        if filt:
            geos = [g for g in geos if filt in g["n"].lower() or filt in g["c"].lower()]
        total_geos = len(geos)
        geos = geos[:50]
        result["geographies"] = geos
        if total_geos > 50:
            result["geo_total"] = total_geos

    if show in ("both", "series"):
        srs = ref["series"]
        if filt:
            srs = [s for s in srs if filt in s["n"].lower() or filt in s["c"].lower()
                   or filt in s.get("cat", "").lower()]
        total_srs = len(srs)
        srs = srs[:50]
        result["series"] = srs
        if total_srs > 50:
            result["series_total"] = total_srs

    return _compact(result)


# ---------------------------------------------------------------------------
# Tool 2: eiu_get_data
# ---------------------------------------------------------------------------

@mcp.tool()
def eiu_get_data(
    geography_codes: list[str],
    series_codes: list[str],
    frequency: str = "Quarterly",
    min_date: str = "",
    max_date: str = "",
) -> str:
    """Fetch EIU forecast/indicator data by country and series codes.

    Use eiu_browse or eiu_search first to find valid codes.

    Args:
        geography_codes: ISO 2-char codes (e.g. ['US', 'BR', 'CN'])
        series_codes: EIU series codes (e.g. ['DGDP', 'DCPI'])
        frequency: 'Yearly', 'Quarterly', or 'Monthly'
        min_date: Start date YYYY-MM-DD (default: 5 years ago)
        max_date: End date YYYY-MM-DD (default: 5 years ahead)
    """
    now = datetime.now(timezone.utc)
    if not min_date:
        min_date = f"{now.year - 5}-01-01"
    if not max_date:
        max_date = f"{now.year + 5}-12-31"

    body = {
        "minDate": f"{min_date}T00:00:00.000Z",
        "frequencyType": frequency,
        "maxDate": f"{max_date}T00:00:00.000Z",
        "geographyCodes": [c.upper() for c in geography_codes],
        "seriesCodes": [c.upper() for c in series_codes],
    }

    try:
        resp = _api_post("/data/searchbycodes", body)
    except Exception as e:
        return _compact({"error": str(e)})

    # Extract data from first page
    all_data = _extract_data_points(resp)

    # Follow pagination if needed
    search_id = resp.get("searchId")
    has_next = resp.get("hasNextPage", False)
    page = 2
    while has_next and search_id and page <= 50:
        try:
            page_resp = _api_get(f"/data/searches/{search_id}", params={"page": page})
            all_data.extend(_extract_data_points(page_resp))
            has_next = page_resp.get("hasNextPage", False)
            page += 1
        except Exception:
            break

    # Cap output for token efficiency
    truncated = False
    if len(all_data) > 200:
        all_data = all_data[:200]
        truncated = True

    result = {"count": len(all_data), "data": all_data}
    if truncated:
        result["truncated"] = True
        result["note"] = "Results capped at 200 points. Narrow date range or reduce countries/series."

    return _compact(result)


def _extract_data_points(resp: dict) -> list:
    """Extract compact data points from an API search response."""
    points = []
    for rec in resp.get("dataPointRecords", []):
        geo_code = rec.get("geographyCode", "")
        s_code = rec.get("seriesCode", "")
        for pt in rec.get("points", []):
            t = pt.get("time", {})
            date_str = t.get("value", "")  # e.g. "2020q1", "2025"
            val = pt.get("valueDisplay", pt.get("value"))
            if val is not None:
                points.append({
                    "g": geo_code,
                    "s": s_code,
                    "d": date_str,
                    "v": val,
                })
    return points


# ---------------------------------------------------------------------------
# Tool 3: eiu_search
# ---------------------------------------------------------------------------

@mcp.tool()
def eiu_search(query: str, limit: int = 25) -> str:
    """Search EIU series by keyword in cached reference data.

    Use this to find series codes before calling eiu_get_data.

    Args:
        query: Search terms (e.g. 'GDP', 'consumer prices', 'exchange rate')
        limit: Max results (default 25, max 100)
    """
    limit = min(max(1, limit), 100)

    try:
        ref = _load_ref_data()
    except Exception as e:
        return _compact({"error": str(e)})

    terms = query.lower().split()
    matches = []
    for s in ref["series"]:
        text = f"{s['n']} {s.get('cat', '')} {s['c']}".lower()
        if all(t in text for t in terms):
            matches.append(s)
            if len(matches) >= limit:
                break

    return _compact({"total": len(matches), "results": matches})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
