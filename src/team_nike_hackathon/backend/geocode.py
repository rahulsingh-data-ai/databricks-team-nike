"""Free-text → ``(lat, lng)`` geocoding via Nominatim.

Used to turn user-typed locations like "Jaipur" or "near Patna" into
coordinates we can rank facilities against. Runs server-side to avoid
browser CORS and to honour Nominatim's rate-limit etiquette (1 req/s,
must include a contact User-Agent).

Returns ``None`` when nothing resolves; callers should treat that as
"search all of India" (origin omitted, results sorted purely by match
score, not distance).
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

import httpx

from .core._config import logger

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "MatchCare/0.1 (hackathon; contact: matchcare@example.com)"
_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

# Hard-coded coordinates for the biggest Indian cities so we always land
# somewhere useful even when Nominatim is rate-limited or unreachable from
# the deployed app's egress. Keys are lowercase, whitespace-collapsed.
_FALLBACK_CITIES: dict[str, tuple[float, float, str]] = {
    "mumbai": (19.0760, 72.8777, "Mumbai, Maharashtra, India"),
    "bombay": (19.0760, 72.8777, "Mumbai, Maharashtra, India"),
    "delhi": (28.6139, 77.2090, "Delhi, India"),
    "new delhi": (28.6139, 77.2090, "New Delhi, India"),
    "bengaluru": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "bangalore": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "hyderabad": (17.3850, 78.4867, "Hyderabad, Telangana, India"),
    "ahmedabad": (23.0225, 72.5714, "Ahmedabad, Gujarat, India"),
    "chennai": (13.0827, 80.2707, "Chennai, Tamil Nadu, India"),
    "madras": (13.0827, 80.2707, "Chennai, Tamil Nadu, India"),
    "kolkata": (22.5726, 88.3639, "Kolkata, West Bengal, India"),
    "calcutta": (22.5726, 88.3639, "Kolkata, West Bengal, India"),
    "surat": (21.1702, 72.8311, "Surat, Gujarat, India"),
    "pune": (18.5204, 73.8567, "Pune, Maharashtra, India"),
    "jaipur": (26.9124, 75.7873, "Jaipur, Rajasthan, India"),
    "lucknow": (26.8467, 80.9462, "Lucknow, Uttar Pradesh, India"),
    "kanpur": (26.4499, 80.3319, "Kanpur, Uttar Pradesh, India"),
    "nagpur": (21.1458, 79.0882, "Nagpur, Maharashtra, India"),
    "indore": (22.7196, 75.8577, "Indore, Madhya Pradesh, India"),
    "thane": (19.2183, 72.9781, "Thane, Maharashtra, India"),
    "bhopal": (23.2599, 77.4126, "Bhopal, Madhya Pradesh, India"),
    "visakhapatnam": (17.6868, 83.2185, "Visakhapatnam, Andhra Pradesh, India"),
    "patna": (25.5941, 85.1376, "Patna, Bihar, India"),
    "vadodara": (22.3072, 73.1812, "Vadodara, Gujarat, India"),
    "ghaziabad": (28.6692, 77.4538, "Ghaziabad, Uttar Pradesh, India"),
    "ludhiana": (30.9010, 75.8573, "Ludhiana, Punjab, India"),
    "agra": (27.1767, 78.0081, "Agra, Uttar Pradesh, India"),
    "nashik": (19.9975, 73.7898, "Nashik, Maharashtra, India"),
    "faridabad": (28.4089, 77.3178, "Faridabad, Haryana, India"),
    "meerut": (28.9845, 77.7064, "Meerut, Uttar Pradesh, India"),
    "rajkot": (22.3039, 70.8022, "Rajkot, Gujarat, India"),
    "varanasi": (25.3176, 82.9739, "Varanasi, Uttar Pradesh, India"),
    "srinagar": (34.0837, 74.7973, "Srinagar, Jammu & Kashmir, India"),
    "amritsar": (31.6340, 74.8723, "Amritsar, Punjab, India"),
    "allahabad": (25.4358, 81.8463, "Prayagraj, Uttar Pradesh, India"),
    "prayagraj": (25.4358, 81.8463, "Prayagraj, Uttar Pradesh, India"),
    "ranchi": (23.3441, 85.3096, "Ranchi, Jharkhand, India"),
    "coimbatore": (11.0168, 76.9558, "Coimbatore, Tamil Nadu, India"),
    "jabalpur": (23.1815, 79.9864, "Jabalpur, Madhya Pradesh, India"),
    "gwalior": (26.2183, 78.1828, "Gwalior, Madhya Pradesh, India"),
    "vijayawada": (16.5062, 80.6480, "Vijayawada, Andhra Pradesh, India"),
    "guwahati": (26.1445, 91.7362, "Guwahati, Assam, India"),
    "chandigarh": (30.7333, 76.7794, "Chandigarh, India"),
    "kochi": (9.9312, 76.2673, "Kochi, Kerala, India"),
    "thiruvananthapuram": (8.5241, 76.9366, "Thiruvananthapuram, Kerala, India"),
    "trivandrum": (8.5241, 76.9366, "Thiruvananthapuram, Kerala, India"),
    "mysuru": (12.2958, 76.6394, "Mysuru, Karnataka, India"),
    "mysore": (12.2958, 76.6394, "Mysuru, Karnataka, India"),
    "bhubaneswar": (20.2961, 85.8245, "Bhubaneswar, Odisha, India"),
    "dehradun": (30.3165, 78.0322, "Dehradun, Uttarakhand, India"),
    "noida": (28.5355, 77.3910, "Noida, Uttar Pradesh, India"),
    "gurgaon": (28.4595, 77.0266, "Gurugram, Haryana, India"),
    "gurugram": (28.4595, 77.0266, "Gurugram, Haryana, India"),
}


class GeocodedPlace(NamedTuple):
    lat: float
    lng: float
    label: str


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _fallback_lookup(query: str) -> GeocodedPlace | None:
    """Resolve a query to a known Indian city, tolerating typos.

    Three passes, in order:

    1. Exact match (whole string is a city key).
    2. Loose substring match — "near Jaipur", "Jaipur, Rajasthan" both hit.
       Pick the longest matched key so "Navi Mumbai" → Mumbai, not Delhi.
    3. Fuzzy match per whitespace-separated token against city keys, using
       ``difflib.SequenceMatcher`` with a 0.78 floor. Catches typos like
       "Jaiphur" → Jaipur, "Mumbi" → Mumbai. The threshold is intentionally
       conservative to avoid false hits ("Delhi" vs "Deli").
    """
    from difflib import SequenceMatcher

    norm = _normalize(query)
    if not norm:
        return None
    if norm in _FALLBACK_CITIES:
        lat, lng, label = _FALLBACK_CITIES[norm]
        return GeocodedPlace(lat=lat, lng=lng, label=label)

    best: tuple[int, GeocodedPlace] | None = None
    for key, (lat, lng, label) in _FALLBACK_CITIES.items():
        if key in norm:
            cand = GeocodedPlace(lat=lat, lng=lng, label=label)
            if best is None or len(key) > best[0]:
                best = (len(key), cand)
    if best is not None:
        return best[1]

    # Fuzzy pass: compare each token in the user query to each city key.
    best_fuzz: tuple[float, GeocodedPlace] | None = None
    tokens = [t for t in norm.replace(",", " ").split() if len(t) >= 3]
    for token in tokens:
        for key, (lat, lng, label) in _FALLBACK_CITIES.items():
            ratio = SequenceMatcher(None, token, key).ratio()
            if ratio >= 0.78 and (best_fuzz is None or ratio > best_fuzz[0]):
                best_fuzz = (
                    ratio,
                    GeocodedPlace(lat=lat, lng=lng, label=label),
                )
    return best_fuzz[1] if best_fuzz else None


@lru_cache(maxsize=512)
def geocode(text: str) -> GeocodedPlace | None:
    """Resolve ``text`` to a ``(lat, lng, label)`` triple, biased to India.

    Tries Nominatim first; on failure (timeout, rate-limit, no hit) falls
    back to the hard-coded city list. Cached for the lifetime of the
    process — Nominatim is rate-limited and most users will retype the
    same handful of city names.
    """
    query = (text or "").strip()
    if not query:
        return None

    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            resp = client.get(
                _NOMINATIM_URL,
                params={
                    "q": query,
                    "countrycodes": "in",
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 0,
                },
            )
            resp.raise_for_status()
            hits = resp.json()
    except Exception as exc:
        logger.warning("Nominatim geocode failed for %r: %s", query, exc)
        return _fallback_lookup(query)

    if not hits:
        return _fallback_lookup(query)

    hit = hits[0]
    try:
        return GeocodedPlace(
            lat=float(hit["lat"]),
            lng=float(hit["lon"]),
            label=hit.get("display_name") or query,
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Nominatim returned unexpected shape for %r: %s", query, exc)
        return _fallback_lookup(query)
