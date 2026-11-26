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
  python atak/package-submission.py [--atak 5.6|5.7|5.8] [--verify [--sdk DIR]] [--out DIR]
Default DIR is ~/Desktop/ATAK Development/CrowdCAD-APKs. Writes
ATAK-Plugin-CrowdCAD_EUD-<ver>-<atak full>-civ-release.zip (e.g. ...-0.1.3-5.6.0-civ-release.zip,
the naming Jon uses for pipeline uploads) plus a .sha256, and prints the list of included files.

--atak 5.6 (default): zip as-is; build.gradle defaults to 5.6.0.
--atak 5.7 / 5.8: patches the default ATAK_VERSION in app/build.gradle inside the zip so the
  pipeline builds for that ATAK (5.7.0 / 5.8.0) without any -P flags. The file on disk is unchanged.

--verify: extracts the zip to ~/iu-tak-build/crowdcad-verify/<name>/, writes a minimal
  local.properties, and runs a clean assembleCivRelease + testCivDebugUnitTest. Use
  --sdk DIR to point at the ATAK SDK; without it the pipeline signing path is used
  (takdev drops its own android_keystore into buildDir). Closest stand-in for the
  pipeline's own Linux build.

Lessons from earlier TAK.gov rejections (see FeatureLink's make-takgov-zip.py):
  * Gradle 9 breaks the pipeline's init script: wrapper must stay 8.x.
  * gradle-wrapper.jar must be in the zip.
  * Generated build/ files must not be (Fortify scans them).
"""
import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

ATAK_DIR = pathlib.Path(__file__).resolve().parent
REPO = ATAK_DIR.parent
TOP = "ATAK-Plugin-CrowdCAD_EUD"      # single top-level folder inside the zip (EUD = the device plugin, not the bridge)

ATAK_VERSIONS = {'5.6': '5.6.0', '5.7': '5.7.0', '5.8': '5.8.0'}

# Repo files outside atak/ that belong in the package: (source, path inside the project).
EXTRA = [
    (REPO / "VERSION", "VERSION"),
    (REPO / "docs" / "COT_FORMAT.md", "docs/COT_FORMAT.md"),
]

# Allowed binaries; anything else binary-looking aborts the build of the zip.
# The iconset zip is plugin content: IconsetInstaller imports it into ATAK on load.
# Rebuild it with iconset/build_iconset.py, never by hand.
ALLOWED_BINARIES = {"gradle/wrapper/gradle-wrapper.jar", ".takdev/aars/takdevlint.aar",
                    "app/src/main/assets/iconsets/CrowdCAD.zip"}
BINARY_EXT = {".apk", ".aab", ".jar", ".aar", ".class", ".so", ".zip", ".keystore", ".jks", ".p12"}
FORBIDDEN = {"local.properties", ".takdev/plugin.properties"}
EXECUTABLE = {"gradlew"}


def tracked_files():
    # Tracked files plus new not-yet-added ones that .gitignore allows (so a fresh file isn't
    # silently left out); ignored files (build/, local.properties, ...) never appear here.
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
                         cwd=ATAK_DIR, check=True, capture_output=True).stdout.decode("utf-8")
    return sorted({p for p in out.split("\0") if p})


def adapt_atak_version(text, atak):
    """Patch the default ATAK_VERSION in build.gradle for a 5.7 (or later) zip.

    build.gradle reads ATAK_VERSION from getProperty('atak.version', '5.6.0'). The pipeline
    doesn't pass -P flags, so for a 5.7 submission the default must be 5.7.0 in the zip.
    """
    full = ATAK_VERSIONS[atak]
    new_text, n = re.subn(
        r"(getProperty\('atak\.version',\s*)'[^']*'",
        lambda m: m.group(0).replace(m.group(0).split("'")[-2], full),
        text,
    )
    if n != 1:
        sys.exit(f"build.gradle: expected one atak.version default, found {n}. Update adapt_atak_version.")
    return new_text


def check_wrapper(files):
    for f in files:
        if f == "gradle/wrapper/gradle-wrapper.properties":
            props = (ATAK_DIR / f).read_text(encoding="utf-8")
            if re.search(r"gradle-9\.", props):
                sys.exit("Gradle 9 wrapper: the TAK.gov init script fails on it. Use 8.x.")
    if "gradle/wrapper/gradle-wrapper.jar" not in files:
        sys.exit("gradle/wrapper/gradle-wrapper.jar missing: the pipeline needs it to bootstrap")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--atak", choices=sorted(ATAK_VERSIONS), default="5.6",
                    help="ATAK major.minor to target (default: 5.6)")
    ap.add_argument("--out", default=str(pathlib.Path.home() / "Desktop" / "ATAK Development" / "CrowdCAD-APKs"))
    ap.add_argument("--verify", action="store_true",
                    help="extract and test-build the zip after writing it")
    ap.add_argument("--sdk", default=None,
                    help="ATAK SDK folder for --verify (contains main.jar + android_keystore)")
    args = ap.parse_args()

    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    entries = []  # (source path, path inside project, bytes override or None)
    file_list = tracked_files()
    check_wrapper(file_list)

    for rel in file_list:
        src = ATAK_DIR / rel
        if not src.is_file():
            continue  # deleted in the working tree but not yet committed
        if rel == "package-submission.py":
            continue  # repo tooling, not part of the plugin
        entries.append((src, rel, None))
    entries += [(src, rel, None) for src, rel in EXTRA]

    problems = []
    for src, rel, _ in entries:
        if rel in FORBIDDEN:
            problems.append(f"{rel}: machine-local, must not ship")
        if pathlib.PurePosixPath(rel).suffix.lower() in BINARY_EXT and rel not in ALLOWED_BINARIES:
            problems.append(f"{rel}: binary not on the allow-list")
        if not src.is_file():
            problems.append(f"{rel}: missing ({src})")
    if problems:
        sys.exit("refusing to package:\n  " + "\n  ".join(problems))

    # For 5.7+, patch the ATAK_VERSION default in-memory (never touches disk).
    if args.atak != "5.6":
        new_entries = []
        for src, rel, override in entries:
            if rel == "app/build.gradle":
                data = adapt_atak_version(src.read_text(encoding="utf-8"), args.atak).encode("utf-8")
                new_entries.append((src, rel, data))
            else:
                new_entries.append((src, rel, override))
        entries = new_entries

    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"{TOP}-{version}-{ATAK_VERSIONS[args.atak]}-civ-release.zip"
    zip_path = out_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel, override in sorted(entries, key=lambda e: e[1]):
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16  # regular file + Unix permissions
            info.create_system = 3                         # Unix, so the modes are honoured
            zf.writestr(info, override if override is not None else src.read_bytes())

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path = zip_path.parent / (zip_path.name + ".sha256")
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    for _, rel, _ in sorted(entries, key=lambda e: e[1]):
        print(f"  {TOP}/{rel}")
    print(f"\n{zip_path}\nsha256 {digest}  ({len(entries)} files)")

    if args.verify:
        verify(zip_path, version, args)


def verify(zip_path, version, args):
    """Extract the zip to a temp folder and run a clean assembleCivRelease."""
    work = pathlib.Path.home() / "iu-tak-build" / "crowdcad-verify" / zip_path.stem
    shutil.rmtree(work, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work)
    proj = work / TOP

    # Read the android sdk.dir from the original local.properties.
    android_sdk = ""
    lp = ATAK_DIR / "local.properties"
    if lp.is_file():
        for line in lp.read_text(encoding="utf-8").splitlines():
            if line.startswith("sdk.dir="):
                android_sdk = line.split("=", 1)[1].strip()
                break

    local_props_lines = [f"sdk.dir={android_sdk}"]
    if args.sdk:
        sdk = str(pathlib.Path(args.sdk)).replace("\\", "/")
        local_props_lines += [
            f"atak.sdk.path={sdk}",
            f"sdk.path={sdk}",
            f"takdev.plugin={sdk}/atak-gradle-takdev.jar",
        ]
    (proj / "local.properties").write_text("\n".join(local_props_lines) + "\n", encoding="utf-8")

    gradlew = str(proj / ("gradlew.bat" if sys.platform == "win32" else "gradlew"))
    cmd = [gradlew, "--no-daemon", "-q", "--project-cache-dir", str(work / ".gradle-cache"),
           "assembleCivRelease", "testCivDebugUnitTest"]
    print(f"\nverifying: clean assembleCivRelease + testCivDebugUnitTest in {proj}")
    if args.sdk:
        print(f"  SDK: {args.sdk}")
    r = subprocess.run(cmd, cwd=proj, shell=(sys.platform == "win32"))
    if r.returncode != 0:
        sys.exit(f"VERIFY FAILED (exit {r.returncode}) in {proj}")
    apks = [str(p) for p in (proj / "app" / "build").rglob("*.apk")]
    print("verify OK:", *apks, sep="\n  ")


if __name__ == "__main__":
    main()
