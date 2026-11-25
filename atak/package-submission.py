#!/usr/bin/env python3
"""Build the TAK.gov third-party pipeline submission zip for the CrowdCAD ATAK plugin.

Why this script exists instead of "zip the atak/ folder":
  * The pipeline gets this Gradle project only, not the repo. app/build.gradle reads the
    plugin version from ../VERSION (the repo root), which is outside the zip, so the
    script copies VERSION in beside settings.gradle (build.gradle prefers that copy).
  * A plain zip of the working folder drags in build/, .gradle/, local.properties (machine
    paths) and takdev's generated .takdev/plugin.properties. Only git-tracked files go in,
    taken from the working tree, so uncommitted edits ARE included. Commit first if the zip
    must match a commit.
  * Windows zip tools drop the executable bit, so the pipeline's Linux runner can't run
    ./gradlew. Entries are written with Unix modes (gradlew 0755).

Usage (from anywhere, stdlib only):
  python atak/package-submission.py [--out DIR]
Default DIR is ~/Desktop/ATAK Development/CrowdCAD-APKs. Writes
ATAK-Plugin-CrowdCAD-<ver>-ATAK-5.6-src.zip plus a .sha256 next to it, and prints the list.
"""
import argparse
import hashlib
import pathlib
import subprocess
import sys
import zipfile

ATAK_DIR = pathlib.Path(__file__).resolve().parent
REPO = ATAK_DIR.parent
TOP = "ATAK-Plugin-CrowdCAD"          # single top-level folder inside the zip
ATAK_MM = "5.6"                       # the SDK build.gradle defaults to (ATAK_VERSION 5.6.0)

# Repo files outside atak/ that belong in the package: (source, path inside the project).
EXTRA = [
    (REPO / "VERSION", "VERSION"),
    (REPO / "docs" / "COT_FORMAT.md", "docs/COT_FORMAT.md"),
]

# Allowed binaries; anything else binary-looking aborts the build of the zip.
ALLOWED_BINARIES = {"gradle/wrapper/gradle-wrapper.jar", ".takdev/aars/takdevlint.aar"}
BINARY_EXT = {".apk", ".aab", ".jar", ".aar", ".class", ".so", ".zip", ".keystore", ".jks", ".p12"}
FORBIDDEN = {"local.properties", ".takdev/plugin.properties"}
EXECUTABLE = {"gradlew"}


def tracked_files():
    # Tracked files plus new not-yet-added ones that .gitignore allows (so a fresh file isn't
    # silently left out); ignored files (build/, local.properties, ...) never appear here.
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
                         cwd=ATAK_DIR, check=True, capture_output=True).stdout.decode("utf-8")
    return sorted({p for p in out.split("\0") if p})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(pathlib.Path.home() / "Desktop" / "ATAK Development" / "CrowdCAD-APKs"))
    args = ap.parse_args()

    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    entries = []  # (source path, path inside project)
    for rel in tracked_files():
        src = ATAK_DIR / rel
        if not src.is_file():
            continue  # deleted in the working tree but not yet committed
        if rel == "package-submission.py":
            continue  # repo tooling, not part of the plugin
        entries.append((src, rel))
    entries += EXTRA

    problems = []
    for src, rel in entries:
        if rel in FORBIDDEN:
            problems.append(f"{rel}: machine-local, must not ship")
        if pathlib.PurePosixPath(rel).suffix.lower() in BINARY_EXT and rel not in ALLOWED_BINARIES:
            problems.append(f"{rel}: binary not on the allow-list")
        if not src.is_file():
            problems.append(f"{rel}: missing ({src})")
    if problems:
        sys.exit("refusing to package:\n  " + "\n  ".join(problems))

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"ATAK-Plugin-CrowdCAD-{version}-ATAK-{ATAK_MM}-src.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel in sorted(entries, key=lambda e: e[1]):
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16  # regular file + Unix permissions
            info.create_system = 3                         # Unix, so the modes are honoured
            zf.writestr(info, src.read_bytes())

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (zip_path.parent / (zip_path.name + ".sha256")).write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    for _, rel in sorted(entries, key=lambda e: e[1]):
        print(f"  {TOP}/{rel}")
    print(f"\n{zip_path}\nsha256 {digest}  ({len(entries)} files)")


if __name__ == "__main__":
    main()
