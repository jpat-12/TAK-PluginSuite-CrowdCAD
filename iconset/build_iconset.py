"""Build the CrowdCAD ATAK iconset zip from the SVGs in ../svgs.

    python iconset/build_iconset.py

The SVGs are Inkscape wrappers around one embedded 256x256 PNG each (no vector shapes), so
this decodes that PNG rather than rasterising the SVG; no cairo or Inkscape needed, only Pillow.

The output matches the layout of ATAK-Plugin-QuickCapture's "Incident Icons.zip", which is
known to import on ATAK 5.6:
    iconset.xml                 <iconset name uid defaultGroup skipResize version>
    CrowdCAD/<name>.png         32x32 RGBA, deflated
A marker's iconsetpath is "<UID>/CrowdCAD/<name>.png" (see ICONS below).

UID and filenames are API: a CoT that carries <usericon iconsetpath=...> resolves only while
both stay the same on every device. Bump VERSION (and ship the new zip) to change the art;
never change UID or a filename once a build has gone out.
"""
import base64
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SVG_DIR = ROOT / "svgs"
OUT_ZIP = ROOT / "atak" / "app" / "src" / "main" / "assets" / "iconsets" / "CrowdCAD.zip"
PNG_DIR = ROOT / "iconset" / "png"   # the same 32px PNGs, for CloudTAK/WebTAK or review

NAME = "CrowdCAD"
GROUP = "CrowdCAD"
VERSION = 1
SIZE = 32
# Fixed forever (see docstring). sha256("crowdcad-tak/iconset") so it looks like other TAK UIDs.
UID = hashlib.sha256(b"crowdcad-tak/iconset").hexdigest()

# source SVG prefix -> iconset filename. Order = order in iconset.xml.
ICONS = [
    ("incdnt-comand-white-solid-genric-ems-plain", "EMS.png"),
    ("incdnt-comand-white-solid-detail-ems-als", "EMS ALS.png"),
    ("incdnt-comand-white-solid-detail-ems-bls", "EMS BLS.png"),
    ("incdnt-comand-white-solid-detail-ems-md1", "EMS MD1.png"),
    ("incdnt-comand-white-solid-detail-ems-sup", "EMS SUP.png"),
]

DATA_URI = re.compile(r'xlink:href="data:image/png;base64,([^"]+)"', re.S)


def embedded_png(svg: Path) -> Image.Image:
    text = svg.read_text(encoding="utf-8")
    found = DATA_URI.findall(text)
    if len(found) != 1:
        sys.exit(f"{svg.name}: expected one embedded PNG, found {len(found)}")
    return Image.open(io.BytesIO(base64.b64decode(re.sub(r"\s+", "", found[0])))).convert("RGBA")


def find_svg(prefix: str) -> Path:
    # Files carry a date suffix (_2026_11_25); take the newest export of each icon.
    matches = sorted(SVG_DIR.glob(prefix + "_*.svg"))
    if not matches:
        sys.exit(f"no SVG matching {prefix}_*.svg in {SVG_DIR}")
    return matches[-1]


def main() -> None:
    pngs = {}
    for prefix, filename in ICONS:
        img = embedded_png(find_svg(prefix)).resize((SIZE, SIZE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        pngs[filename] = buf.getvalue()

    xml = [f'<iconset name="{NAME}" uid="{UID}" defaultGroup="{GROUP}" '
           f'skipResize="false" version="{VERSION}">']
    xml += [f'  <icon name="{f}" />' for f in pngs]
    xml.append("</iconset>")

    OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("iconset.xml", "\n".join(xml) + "\n")
        for filename, data in pngs.items():
            z.writestr(f"{GROUP}/{filename}", data)

    PNG_DIR.mkdir(parents=True, exist_ok=True)
    for filename, data in pngs.items():
        (PNG_DIR / filename).write_bytes(data)

    print(f"wrote {OUT_ZIP.relative_to(ROOT)} ({len(pngs)} icons, uid {UID})")
    for filename in pngs:
        print(f"  {UID}/{GROUP}/{filename}")


if __name__ == "__main__":
    main()
