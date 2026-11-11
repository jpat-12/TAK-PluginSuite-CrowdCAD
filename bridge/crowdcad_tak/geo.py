"""Where a CrowdCAD post or zone is on the earth.

CrowdCAD has no coordinates of its own: a post is (x, y) as a *percentage of its layer's map
image*, and a call or team "location" is just a post's name. A layer can be placed on the
earth only if it has `geoBounds` (set when the venue map was built by GeoJSON import) or the
operator supplied bounds for it in this bridge's config (`layer_bounds`).

CrowdCAD maps lat/lng onto the image linearly (src/lib/markerUtils.ts latLngToPercent), so
this is the exact inverse of that — not Web Mercator. Don't "fix" it to Mercator: over a
venue-sized area the difference is centimetres, and matching CrowdCAD exactly is what keeps a
post where the dispatcher sees it.
"""


def event_layers(event):
    """The event's map layers, resolved the way CrowdCAD's own getEventVenueLayers does
    (src/lib/zones.ts): the venue's layers if it has any, else one legacy layer built from
    the event's posts."""
    venue = event.get("venue") or {}
    layers = venue.get("layers") or []
    if layers:
        return layers
    return [{"id": "legacy-layer", "name": venue.get("name") or "Main Floor",
             "posts": event.get("eventPosts") or [], "mapUrl": venue.get("mapUrl")}]


def _valid_bounds(bounds):
    try:
        north, south = float(bounds["north"]), float(bounds["south"])
        east, west = float(bounds["east"]), float(bounds["west"])
    except (KeyError, TypeError, ValueError):
        return None
    if north == south or east == west:
        return None
    return {"north": north, "south": south, "east": east, "west": west}


def layer_bounds(layer, overrides=None):
    """Operator override first (it exists precisely because the layer's own is missing or
    wrong), then the layer's GIS-import bounds."""
    override = (overrides or {}).get(layer.get("id"))
    return _valid_bounds(override) if override else _valid_bounds(layer.get("geoBounds"))


def percent_to_latlon(x, y, bounds):
    lat = bounds["north"] - (float(y) / 100.0) * (bounds["north"] - bounds["south"])
    lon = bounds["west"] + (float(x) / 100.0) * (bounds["east"] - bounds["west"])
    return round(lat, 7), round(lon, 7)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def post_location(name, event, overrides=None):
    """(lat, lon, layer_name) for the post called `name`, or None if it can't be placed.

    Exact name match, first layer that can place it wins — the same rule CrowdCAD's
    findZonesForPost uses, so a post on two floors resolves to the same one both apps pick.
    A post's own lat/lng (GIS-import provenance) is only a fallback: CrowdCAD renders from
    x/y and never updates lat/lng when a post is dragged, so x/y is the live position.
    """
    if not name:
        return None
    fallback = None
    for layer in event_layers(event):
        bounds = layer_bounds(layer, overrides)
        for post in layer.get("posts") or []:
            if isinstance(post, str) or post.get("name") != name:
                continue
            if bounds and _number(post.get("x")) and _number(post.get("y")):
                lat, lon = percent_to_latlon(post["x"], post["y"], bounds)
                return lat, lon, layer.get("name") or ""
            if fallback is None and _number(post.get("lat")) and _number(post.get("lng")):
                fallback = (round(post["lat"], 7), round(post["lng"], 7), layer.get("name") or "")
    return fallback


def zone_shapes(event, overrides=None):
    """Every drawable zone as (layer, zone, [(lat, lon), ...]) — only layers that can be placed."""
    shapes = []
    for layer in event_layers(event):
        bounds = layer_bounds(layer, overrides)
        if not bounds:
            continue
        for zone in layer.get("zones") or []:
            points = [p for p in zone.get("points") or [] if _number(p.get("x")) and _number(p.get("y"))]
            if len(points) >= 3:
                shapes.append((layer, zone, [percent_to_latlon(p["x"], p["y"], bounds) for p in points]))
    return shapes


def placed_posts(event, overrides=None):
    """Every post that can be placed, as (layer, post, lat, lon)."""
    out = []
    for layer in event_layers(event):
        for post in layer.get("posts") or []:
            if isinstance(post, str):
                continue
            where = post_location(post.get("name"), {"venue": {"layers": [layer]}}, overrides)
            if where:
                out.append((layer, post, where[0], where[1]))
    return out
