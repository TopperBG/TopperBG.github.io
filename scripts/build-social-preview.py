#!/usr/bin/env python3
"""Build the 1200x630 Open Graph preview for EnergoKarta Bulgaria."""

from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "map" / "index.html"
SOLAR_CACHE_PATH = ROOT / "data" / "agkk-built-vei-cache.json"
WIND_PATH = ROOT / "data" / "wind-turbines-bg.json"
OUTPUT_PATH = ROOT / "map" / "assets" / "energokarta-preview.jpg"

WIDTH, HEIGHT = 1200, 630
BBOX = (22.0, 40.8, 29.2, 44.4)
SATELLITE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/export?"
    + urllib.parse.urlencode(
        {
            "bbox": ",".join(map(str, BBOX)),
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{WIDTH},{HEIGHT}",
            "format": "jpg",
            "f": "image",
        }
    )
)
AGKK_QUERY_URL = (
    "https://inspire.cadastre.bg/arcgis/rest/services/"
    "Cadastral_Parcel/MapServer/0/query"
)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def load_js_json(source: str, name: str):
    match = re.search(rf"(?:const|let|var)\s+{re.escape(name)}\s*=\s*", source)
    if not match:
        raise RuntimeError(f"Could not find JavaScript data variable: {name}")
    value, _ = json.JSONDecoder().raw_decode(source, match.end())
    return value


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "EnergoKarta-Bulgaria-social-preview/1.0"}
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        destination.write_bytes(response.read())


def project(point):
    lon, lat = point
    min_lon, min_lat, max_lon, max_lat = BBOX
    x = (lon - min_lon) / (max_lon - min_lon) * WIDTH
    y = (max_lat - lat) / (max_lat - min_lat) * HEIGHT
    return (round(x), round(y))


def geometry_rings(geometry):
    if not geometry:
        return
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if kind == "Polygon":
        yield from coordinates
    elif kind == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon


def draw_geometry(draw: ImageDraw.ImageDraw, geometry, *, fill, outline, width=1):
    for ring in geometry_rings(geometry):
        points = [project(point) for point in ring if len(point) >= 2]
        if len(points) >= 3:
            draw.polygon(points, fill=fill)
            draw.line(points + [points[0]], fill=outline, width=width, joint="curve")


def fetch_planned_parcels(projects):
    refs = list(
        dict.fromkeys(
            ref for item in projects for ref in item.get("parcels", []) if ref
        )
    )
    features = []
    for offset in range(0, len(refs), 80):
        chunk = refs[offset : offset + 80]
        params = {
            "where": "nationalcadastralref IN ("
            + ",".join(f"'{ref}'" for ref in chunk)
            + ")",
            "outFields": "nationalcadastralref,areavalue,areavalue_uom",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
        }
        request = urllib.request.Request(
            AGKK_QUERY_URL,
            data=urllib.parse.urlencode(params).encode("utf-8"),
            headers={"User-Agent": "EnergoKarta-Bulgaria-social-preview/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
            for feature in payload.get("features", []):
                rings = feature.get("geometry", {}).get("rings")
                if rings:
                    features.append(
                        {
                            "type": "Feature",
                            "properties": feature.get("attributes", {}),
                            "geometry": {"type": "Polygon", "coordinates": rings},
                        }
                    )
        except Exception as error:  # Keep the preview build useful if AGKK is briefly down.
            print(f"AGKK batch {offset // 80 + 1} skipped: {error}")
        if offset + 80 < len(refs):
            time.sleep(0.35)
    return features


def rounded_panel(layer, box, radius, fill, outline=None, width=1):
    draw = ImageDraw.Draw(layer, "RGBA")
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw, x, y, label, color, font):
    dot_radius = 6
    left_padding, right_padding = 15, 15
    text_box = draw.textbbox((0, 0), label, font=font)
    text_width = text_box[2] - text_box[0]
    width = left_padding + 17 + text_width + right_padding
    draw.rounded_rectangle(
        (x, y, x + width, y + 34),
        radius=17,
        fill=(12, 23, 31, 218),
        outline=(255, 255, 255, 62),
        width=1,
    )
    draw.ellipse(
        (x + left_padding, y + 11, x + left_padding + 2 * dot_radius, y + 23),
        fill=color,
        outline=(255, 255, 255, 210),
        width=1,
    )
    draw.text((x + left_padding + 19, y + 8), label, font=font, fill=(255, 255, 255, 245))
    return x + width + 9


def build():
    source = HTML_PATH.read_text(encoding="utf-8")
    provinces = load_js_json(source, "provinces")
    fires = load_js_json(source, "fires")
    planned_projects = load_js_json(source, "cadastralProjects")
    solar_cache = json.loads(SOLAR_CACHE_PATH.read_text(encoding="utf-8"))
    wind_data = json.loads(WIND_PATH.read_text(encoding="utf-8"))

    work_dir = ROOT / ".social-preview-cache"
    work_dir.mkdir(exist_ok=True)
    satellite_path = work_dir / "bulgaria-satellite.jpg"
    if not satellite_path.exists():
        download(SATELLITE_URL, satellite_path)

    base = Image.open(satellite_path).convert("RGB").resize((WIDTH, HEIGHT))
    base = ImageEnhance.Contrast(base).enhance(1.08)
    base = ImageEnhance.Color(base).enhance(0.90)
    base = ImageEnhance.Brightness(base).enhance(0.82)

    # Keep Bulgaria visually dominant and dim the surrounding countries.
    country_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    mask_draw = ImageDraw.Draw(country_mask)
    for feature in provinces.get("features", []):
        for ring in geometry_rings(feature.get("geometry")):
            points = [project(point) for point in ring if len(point) >= 2]
            if len(points) >= 3:
                mask_draw.polygon(points, fill=255)
    country_mask = country_mask.filter(ImageFilter.GaussianBlur(1.2))
    outside = Image.new("RGB", (WIDTH, HEIGHT), (4, 12, 17))
    outside = Image.blend(base, outside, 0.58)
    base = Image.composite(base, outside, country_mask)

    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Built solar cadastral parcels.
    for item in solar_cache.get("features", {}).values():
        draw_geometry(
            draw,
            item.get("feature", {}).get("geometry"),
            fill=(255, 187, 0, 105),
            outline=(255, 222, 86, 245),
            width=2,
        )

    # Planned PUP/PI parcels, fetched from the same public AGKK service as the map.
    planned_cache_path = work_dir / "planned-parcels.json"
    if planned_cache_path.exists():
        planned_features = json.loads(planned_cache_path.read_text(encoding="utf-8"))
    else:
        planned_features = fetch_planned_parcels(planned_projects)
        planned_cache_path.write_text(
            json.dumps(planned_features, ensure_ascii=False), encoding="utf-8"
        )
    for feature in planned_features:
        draw_geometry(
            draw,
            feature.get("geometry"),
            fill=(58, 128, 255, 86),
            outline=(112, 177, 255, 235),
            width=2,
        )

    # Province outlines, matching the live map's high-contrast satellite style.
    for feature in provinces.get("features", []):
        for ring in geometry_rings(feature.get("geometry")):
            points = [project(point) for point in ring if len(point) >= 2]
            if len(points) >= 2:
                draw.line(points, fill=(0, 0, 0, 175), width=4, joint="curve")
                draw.line(points, fill=(255, 255, 255, 215), width=2, joint="curve")

    # Wind turbines.
    for turbine in wind_data.get("turbines", []):
        x, y = project((turbine.get("lon"), turbine.get("lat")))
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            draw.line((x - 2, y, x + 2, y), fill=(77, 211, 235, 235), width=1)
            draw.line((x, y - 2, x, y + 2), fill=(77, 211, 235, 235), width=1)

    # All mapped fires from 2021–2026, with area encoded in circle size.
    for fire in sorted(fires, key=lambda item: float(item.get("area_ha") or 0)):
        x, y = project((fire.get("lon"), fire.get("lat")))
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            continue
        area = max(1.0, float(fire.get("area_ha") or 1))
        radius = max(2, min(10, round(1.5 + math.log10(area + 1) * 2.1)))
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(219, 64, 98, 150),
            outline=(255, 226, 232, 220),
            width=1,
        )

    base = Image.alpha_composite(base.convert("RGBA"), overlay)

    # Dark top gradient gives the title reliable contrast over any satellite tile.
    gradient = Image.new("RGBA", (WIDTH, 240), (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient)
    for y in range(240):
        alpha = round(190 * (1 - y / 240) ** 1.35)
        gradient_draw.line((0, y, WIDTH, y), fill=(2, 10, 16, alpha))
    base.alpha_composite(gradient, (0, 0))

    ui = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    rounded_panel(
        ui,
        (26, 24, 775, 171),
        radius=24,
        fill=(7, 19, 26, 220),
        outline=(255, 255, 255, 78),
        width=2,
    )
    ui_draw = ImageDraw.Draw(ui, "RGBA")
    title_font = ImageFont.truetype(FONT_BOLD, 48)
    subtitle_font = ImageFont.truetype(FONT_REGULAR, 23)
    pill_font = ImageFont.truetype(FONT_BOLD, 15)
    small_font = ImageFont.truetype(FONT_REGULAR, 14)
    url_font = ImageFont.truetype(FONT_BOLD, 17)

    ui_draw.text(
        (58, 45),
        "ЕнергоКарта България",
        font=title_font,
        fill=(255, 255, 255, 255),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 120),
    )
    ui_draw.text(
        (60, 111),
        "Интерактивен атлас на енергията, територията\nи природните рискове",
        font=subtitle_font,
        fill=(224, 237, 242, 245),
        spacing=4,
    )

    pill_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill_layer, "RGBA")
    x, y = 28, 548
    x = pill(pill_draw, x, y, "ФЕЦ", (255, 187, 0, 255), pill_font)
    x = pill(pill_draw, x, y, "ВяЕИ", (77, 211, 235, 255), pill_font)
    x = pill(pill_draw, x, y, "ПУП/ПИ", (85, 146, 255, 255), pill_font)
    x = pill(pill_draw, x, y, "Пожари 2021–2026", (219, 64, 98, 255), pill_font)

    url_box = (842, 548, 1172, 598)
    pill_draw.rounded_rectangle(
        url_box,
        radius=20,
        fill=(7, 19, 26, 225),
        outline=(255, 255, 255, 72),
        width=1,
    )
    pill_draw.text(
        (868, 562),
        "topperbg.github.io/map/",
        font=url_font,
        fill=(255, 255, 255, 250),
    )
    pill_draw.text(
        (925, 607),
        "Esri World Imagery · АГКК · OSM · EFFIS/Copernicus",
        font=small_font,
        fill=(255, 255, 255, 190),
        anchor="mm",
    )

    base = Image.alpha_composite(base, ui)
    base = Image.alpha_composite(base, pill_layer)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(
        OUTPUT_PATH,
        format="JPEG",
        quality=91,
        optimize=True,
        progressive=True,
        dpi=(96, 96),
    )
    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
