"""
Geo-imagery — verify a place visually and surface photos taken there.

Ties directly into PAW's geotime map:
  • street_view_url(lat, lon)   → an interactive Google Street View link at that
    exact spot (no key) so you can visually confirm a sighting location.
  • nearby_photos(lat, lon)     → geotagged photos taken near the point, via the
    Flickr API when FLICKR_KEY is set; otherwise a Flickr-map link. Photos taken
    at a location can reveal who was there, or match a photo's background.

Everything degrades cleanly when a key is absent.
"""
from __future__ import annotations

import os

_TIMEOUT = 12


def street_view_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"


def static_streetview_url(lat: float, lon: float, size: str = "600x300") -> str | None:
    """A static Street View thumbnail — only when GOOGLE_MAPS_KEY is set."""
    key = os.environ.get("GOOGLE_MAPS_KEY", "").strip()
    if not key:
        return None
    return (f"https://maps.googleapis.com/maps/api/streetview?size={size}"
            f"&location={lat},{lon}&key={key}")


def flickr_map_url(lat: float, lon: float) -> str:
    return f"https://www.flickr.com/map?&fLat={lat}&fLon={lon}&zl=15"


def nearby_photos(lat: float, lon: float, radius_km: float = 1.0, limit: int = 20) -> dict:
    """Geotagged photos near a point (Flickr). Falls back to a map link with no key."""
    key = os.environ.get("FLICKR_KEY", "").strip()
    if not key:
        return {"configured": False, "photos": [],
                "map_url": flickr_map_url(lat, lon),
                "note": "Set FLICKR_KEY to pull geotagged photos automatically. "
                        "Meanwhile, open the Flickr map link."}
    import requests
    try:
        r = requests.get(
            "https://www.flickr.com/services/rest/",
            params={
                "method": "flickr.photos.search", "api_key": key,
                "lat": lat, "lon": lon, "radius": max(0.1, min(radius_km, 32)),
                "radius_units": "km", "has_geo": 1, "per_page": limit,
                "extras": "geo,url_m,url_q,date_taken,owner_name",
                "format": "json", "nojsoncallback": 1, "sort": "relevance",
            },
            timeout=_TIMEOUT,
        )
        if not r.ok:
            return {"configured": True, "photos": [], "error": f"HTTP {r.status_code}",
                    "map_url": flickr_map_url(lat, lon)}
        data = r.json()
        if data.get("stat") != "ok":
            return {"configured": True, "photos": [], "error": data.get("message", "flickr error"),
                    "map_url": flickr_map_url(lat, lon)}
        photos = []
        for p in data.get("photos", {}).get("photo", [])[:limit]:
            pid, owner = p.get("id"), p.get("owner")
            photos.append({
                "title":     p.get("title", ""),
                "owner":     p.get("ownername", "") or owner,
                "date_taken": p.get("datetaken", ""),
                "thumb":     p.get("url_q") or p.get("url_m", ""),
                "image":     p.get("url_m", ""),
                "lat":       float(p["latitude"]) if p.get("latitude") else None,
                "lon":       float(p["longitude"]) if p.get("longitude") else None,
                "page":      f"https://www.flickr.com/photos/{owner}/{pid}",
            })
        return {"configured": True, "photos": photos, "count": len(photos),
                "map_url": flickr_map_url(lat, lon)}
    except Exception as exc:
        return {"configured": True, "photos": [], "error": str(exc),
                "map_url": flickr_map_url(lat, lon)}


def run_sync(lat=None, lon=None, location: str = "", radius_km: float = 1.0) -> dict:
    """
    Geo-imagery for a point. Accepts lat/lon directly, or a place name to geocode.
    Returns Street View link, a static thumbnail (if key), and nearby photos.
    """
    if (lat is None or lon is None) and location:
        try:
            from skills.core.watson_tools import _geocode
            g = _geocode(location)
            if g:
                lat, lon = g["lat"], g["lon"]
        except Exception:
            pass
    if lat is None or lon is None:
        return {"error": "Provide lat/lon or a geocodable location."}
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return {"error": "Invalid coordinates."}

    photos = nearby_photos(lat, lon, radius_km=radius_km)
    return {
        "lat": lat, "lon": lon, "location": location,
        "street_view":  street_view_url(lat, lon),
        "static_streetview": static_streetview_url(lat, lon),
        "flickr_map":   flickr_map_url(lat, lon),
        "google_maps":  f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
        "nearby_photos": photos.get("photos", []),
        "photos_configured": photos.get("configured", False),
        "note": photos.get("note", ""),
    }
