"""Build a downloadable macOS patch application with no external Python dependency."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

from .patch import ROOT, copy_app, digest, load_payload, write_json


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def archive_file(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    # File timestamps must not create a different runtime build ID for the
    # exact same source and payload on a subsequent checkout/build.
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, path.read_bytes())


def archive_source(destination: Path) -> None:
    entries = []
    for folder in ("src", "tests", "tools", "patches", "packaging", "docs", "licenses"):
        entries.extend(p for p in (ROOT / folder).rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts and p.suffix != ".pyc")
    entries.extend(ROOT / name for name in (
        "CMakeLists.txt", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "README.en.md",
        "pyproject.toml", "uv.lock", "patch.py", ".gitignore", ".gitattributes"))
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(entries):
            archive_file(archive, path, str(path.relative_to(ROOT)))


def smoke_runtime(app: Path) -> None:
    executable = app / "Contents/MacOS/EndPlayDesktopRuntime"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "_PYI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    result = subprocess.run([str(executable), "--runtime-check"], cwd="/tmp", env=env,
                            capture_output=True, text=True, check=True, timeout=30)
    report = json.loads(result.stdout)
    if (not report.get("frozen") or not report.get("sidecar_import") or not report.get("lifecycle_import")
            or report.get("maafw_loaded") is not False):
        raise ValueError("Frozen runtime check failed")
    print("Frozen runtime:", json.dumps(report))
    requests = [{"op": "connected", "args": []}, {"op": "close", "args": []}]
    wire = b""
    for request in requests:
        body = json.dumps(request).encode()
        wire += struct.pack("!I", len(body)) + body
    result = subprocess.run([
        str(executable), "-m", "tools.EndPlayDesktop", "--endpoint", "/tmp/endplaydesktop-not-connected.json",
        "--maatools-address", "127.0.0.1:1", "sidecar",
    ], input=wire, cwd="/tmp", env=env, capture_output=True, check=True, timeout=30)
    remaining = result.stdout
    for expected in (False, True):
        size = struct.unpack("!I", remaining[:4])[0]
        reply = json.loads(remaining[4:4 + size])
        if reply.get("ok") is not True or reply.get("result") is not expected or reply.get("payload_size") != 0:
            raise ValueError("Frozen sidecar protocol check failed")
        remaining = remaining[4 + size:]
    if remaining:
        raise ValueError("Unexpected sidecar output")
    print("Frozen sidecar protocol: passed without connecting to the game")
    agent_env = {**env, "PI_CONTROLLER": '{"name":"EndPlayDesktop","type":"PlayCover"}',
                 "ENDPLAYDESKTOP_ADAPTER_LOADED": "1", "ENDPLAYDESKTOP_CONFIG": "/unused"}
    program = (
        "import json,os,sys; "
        "assert json.loads(os.environ['PI_CONTROLLER'])['type']=='MacOS'; "
        "assert 'ENDPLAYDESKTOP_CONFIG' not in os.environ; "
        "assert 'ENDPLAYDESKTOP_ADAPTER_LOADED' not in os.environ; "
        "assert sys.argv[1:] == ['argument with spaces','ipc:///tmp/maa.sock']"
    )
    subprocess.run([str(executable), "-m", "tools.EndPlayDesktop", "agent-exec", "--",
                    sys.executable, "-c", program, "argument with spaces", "ipc:///tmp/maa.sock"],
                   cwd="/tmp", env=agent_env, capture_output=True, check=True, timeout=30)
    print("Frozen Agent forwarding: passed with desktop kind and original arguments")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=ROOT / ".cache/payloads/desktop")
    args = parser.parse_args(argv)
    payload = args.payload.resolve(strict=True)
    manifest, _ = load_payload(payload)
    if manifest["format"] != 4:
        raise ValueError("Rebuild the external controller payload before bundling; do not ship the legacy MXU replacement")
    version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.MULTILINE).group(1)
    assets = ROOT / ".cache/app-assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    runtime = assets / "runtime_source/tools/EndPlayDesktop"
    runtime.mkdir(parents=True)
    (runtime.parent / "__init__.py").write_text("")
    for name in ("__init__.py", "__main__.py", "cli.py", "client.py", "capture.py", "controller.py", "maa_controller.py", "pitch.py", "sidecar.py", "lifecycle.py", "log_output.py", "agent_launch.py"):
        shutil.copy2(ROOT / "tools/EndPlayDesktop" / name, runtime / name)
    with zipfile.ZipFile(assets / "payloads.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ["manifest.json", *(entry["path"] for entry in manifest["files"].values())]:
            archive_file(archive, payload / name, "desktop/" + name)
    archive_source(assets / "EndPlayDesktop-source.zip")
    build_id = hashlib.sha256((digest(assets / "EndPlayDesktop-source.zip") + digest(assets / "payloads.zip")).encode()).hexdigest()[:12]
    write_json(assets / "distribution.json", {
        "format": 2, "version": version, "build_id": build_id, "payload": "desktop",
    })
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(ROOT / ".cache/app-dist"),
        "--workpath", str(ROOT / ".cache/app-build"), str(ROOT / "packaging/EndPlayDesktopPatch.spec"))
    built = ROOT / ".cache/app-dist/EndPlayDesktopPatch.app"
    smoke_runtime(built)
    package_name = f"EndPlayDesktop-{version}-macos-arm64"
    output = ROOT / "dist" / package_name
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy_app(built, output / built.name)
    shutil.copy2(ROOT / "build/libEndPlayDesktop.dylib", output / "libEndPlayDesktop.dylib")
    shutil.copy2(assets / "EndPlayDesktop-source.zip", output / "EndPlayDesktop-source.zip")
    shutil.copy2(ROOT / "docs/one-click.md", output / "使用说明.md")
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    zip_path = ROOT / "dist" / (package_name + ".zip")
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(output), str(zip_path))
    dmg_path = ROOT / "dist" / (package_name + ".dmg")
    run("hdiutil", "create", "-volname", "EndPlayDesktop", "-srcfolder", str(output), "-format", "UDZO", "-ov", str(dmg_path))
    print(json.dumps({"app": str(output / built.name), "zip": str(zip_path), "dmg": str(dmg_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
