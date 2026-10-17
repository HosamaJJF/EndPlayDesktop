"""Patch an existing MaaEnd.app while preserving its identity and task settings."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import json5


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = "EndPlayDesktop"
EXCLUDED = ("LaunchGamePC", "CloseGamePC")
RECEIPT = Path("Contents/Resources/EndPlayDesktop/receipt.json")
DEFAULT_APP = Path("/Applications/MaaEnd.app")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def read_json(path: Path) -> dict:
    value = json5.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def contained(root: Path, relative: str | Path) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes its root: {relative}")
    return path


def app_info(app: Path) -> tuple[dict, Path, str]:
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    executable = info["CFBundleExecutable"]
    if Path(executable).name != executable:
        raise ValueError("Invalid CFBundleExecutable")
    directory = app / "Contents/MacOS"
    interface = read_json(directory / "interface.json")
    version = interface.get("version")
    if interface.get("name") != "MaaEnd" or not isinstance(version, str) or not version:
        raise ValueError("The target must be a versioned MaaEnd app")
    if version != info.get("CFBundleShortVersionString"):
        raise ValueError("Bundle and interface versions disagree")
    return info, directory, version


def documents(directory: Path) -> dict[Path, dict]:
    pending = [directory / "interface.json"]
    found = {}
    while pending:
        path = pending.pop()
        if path in found:
            continue
        data = read_json(path)
        found[path] = data
        imports = data.get("import", [])
        if not isinstance(imports, list) or not all(isinstance(item, str) for item in imports):
            raise ValueError(f"Unsupported import list: {path}")
        pending.extend(contained(directory, item) for item in imports)
    return found


def update_filters(value: object, windows: set[str], blocked: bool = False) -> int:
    changed = 0
    if isinstance(value, dict):
        blocked = blocked or any(value.get(key) in EXCLUDED for key in ("name", "entry"))
        for key, item in value.items():
            if key == "controller" and isinstance(item, list) and all(isinstance(name, str) for name in item):
                updated = list(item)
                if blocked:
                    updated = [name for name in item if name != CONTROLLER]
                elif windows.intersection(item) and CONTROLLER not in item:
                    updated.append(CONTROLLER)
                if updated != item:
                    value[key] = updated
                    changed += 1
            else:
                child_blocked = blocked or any(key.startswith(name) for name in EXCLUDED)
                changed += update_filters(item, windows, child_blocked)
    elif isinstance(value, list):
        changed += sum(update_filters(item, windows, blocked) for item in value)
    return changed


def resource_changes(directory: Path, runtime: Path) -> tuple[dict[Path, dict], int]:
    directory = directory.resolve()
    runtime = runtime.resolve()
    python = runtime / ".venv/bin/python"
    if not python.is_file() or not (runtime / "tools/EndPlayDesktop/sidecar.py").is_file():
        raise ValueError("Missing EndPlayDesktop runtime; run uv sync in its repository first")
    source = documents(directory)
    interface_path = directory / "interface.json"
    interface = source[interface_path]
    windows = {c["name"] for c in interface["controller"] if c.get("type") == "Win32"}
    if not windows:
        raise ValueError("No Windows controller definitions found; review this MaaEnd version")
    controller = {
        "name": CONTROLLER, "type": CONTROLLER, "display_short_side": 720,
        "endplaydesktop": {"python": str(python), "project_dir": str(runtime)},
    }
    changes = {}
    filters = 0
    for path, original in source.items():
        updated = copy.deepcopy(original)
        filters += update_filters(updated, windows)
        if path == interface_path:
            existing = [c for c in updated["controller"] if c["name"] == CONTROLLER]
            if len(existing) > 1:
                raise ValueError("Duplicate EndPlayDesktop controller definitions")
            if existing and existing[0].get("type") != CONTROLLER:
                raise ValueError("EndPlayDesktop name is occupied by another controller type")
            if existing:
                updated["controller"][updated["controller"].index(existing[0])] = controller
            else:
                index = next((i + 1 for i, c in enumerate(updated["controller"]) if c.get("type") == "PlayCover"), len(updated["controller"]))
                updated["controller"].insert(index, controller)
        if updated != original:
            changes[path.relative_to(directory)] = updated
    return changes, filters


def load_payload(payload: Path, app: Path) -> tuple[dict, str]:
    manifest = read_json(payload / "manifest.json")
    info, directory, version = app_info(app)
    if manifest.get("format") != 1 or manifest.get("maaend_version") != version:
        raise ValueError("Payload does not match this MaaEnd version; rebuild after updating MaaEnd")
    if manifest.get("architecture") != "arm64":
        raise ValueError("Only the Apple Silicon payload is supported")
    receipt_path = app / RECEIPT
    receipt = read_json(receipt_path) if receipt_path.exists() else None
    base = receipt["base"] if receipt else {
        "mxu": digest(directory / info["CFBundleExecutable"]),
        "go-service": digest(directory / "agent/go-service"),
    }
    if base != manifest["base"]:
        raise ValueError("App executables differ from the payload baseline; build for this exact app")
    for name in ("mxu", "go-service"):
        if digest(contained(payload, manifest["files"][name]["path"])) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Corrupt patch payload: {name}")
    return manifest, digest(payload / "manifest.json")


def running(app: Path) -> bool:
    info, directory, _ = app_info(app)
    executable = directory / info["CFBundleExecutable"]
    output = subprocess.check_output(["ps", "-axo", "comm="], text=True)
    return any(Path(line.strip()).resolve() == executable for line in output.splitlines() if line.strip())


def verify_app(app: Path) -> None:
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def verify_original(app: Path) -> None:
    # Official packages can carry a resource envelope created on another
    # filesystem (including different Unicode filename normalization). Check
    # executable integrity here; validate the regenerated full seal after patching.
    subprocess.run(["codesign", "--verify", "--strict", "--ignore-resources", str(app)], check=True)


def copy_app(source: Path, destination: Path) -> None:
    if sys.platform == "darwin":
        # Upstream signs non-Mach-O files through extended attributes, which
        # Python's copytree on macOS does not preserve.
        subprocess.run(["ditto", "--rsrc", "--extattr", "--acl", str(source), str(destination)], check=True)
    else:
        shutil.copytree(source, destination, symlinks=True)


def sign_app(app: Path, resources: list[Path]) -> None:
    # Upstream treats JSON below Contents/MacOS as nested signed objects.
    # Refresh only edited JSON signatures; keep every existing library and
    # C++ Agent byte-for-byte intact rather than re-signing all nested code.
    for path in resources:
        result = subprocess.run(["codesign", "--force", "--sign", "-", str(path)],
                                capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"Cannot sign {path.name}: {result.stderr.strip()}")
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    verify_app(app)


def swap_app(app: Path, replacement: Path) -> None:
    previous = app.parent / f".{app.name}.endplaydesktop-{uuid.uuid4().hex}"
    app.rename(previous)
    try:
        replacement.rename(app)
    except BaseException:
        previous.rename(app)
        raise
    shutil.rmtree(previous)


def apply_patch(app: Path, payload: Path, runtime: Path, backups: Path) -> dict:
    if running(app):
        raise ValueError("Quit MaaEnd before applying the patch")
    manifest, payload_id = load_payload(payload, app)
    info, directory, version = app_info(app)
    changes, filters = resource_changes(directory, runtime)
    existing = read_json(app / RECEIPT) if (app / RECEIPT).exists() else {}
    if existing.get("payload_id") == payload_id and not changes:
        verify_app(app)
        return {"status": "already_applied", "version": version}
    verify_original(app)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup = backups / stamp
    backup.mkdir(parents=True, exist_ok=False)
    copy_app(app, backup / "MaaEnd.app")
    write_json(backup / "backup.json", {"format": 1, "app": str(app), "maaend_version": version})
    with tempfile.TemporaryDirectory(prefix=".endplaydesktop-", dir=app.parent) as temporary:
        staged = Path(temporary) / app.name
        copy_app(app, staged)
        target = staged / "Contents/MacOS"
        for relative, value in changes.items():
            write_json(target / relative, value)
        destinations = {"mxu": target / info["CFBundleExecutable"], "go-service": target / "agent/go-service"}
        for name, destination in destinations.items():
            shutil.copy2(contained(payload, manifest["files"][name]["path"]), destination)
            destination.chmod(0o755)
        write_json(staged / RECEIPT, {
            "format": 1, "payload_id": payload_id, "maaend_version": version,
            "base": manifest["base"], "backup": str(backup), "runtime": str(runtime),
        })
        sign_app(staged, [target / relative for relative in changes])
        swap_app(app, staged)
    return {"status": "applied", "version": version, "changed_resource_files": len(changes),
            "changed_controller_filters": filters, "backup": str(backup)}


def restore(app: Path, backup: Path) -> dict:
    if running(app):
        raise ValueError("Quit MaaEnd before restoring the app")
    metadata = read_json(backup / "backup.json")
    if metadata.get("format") != 1 or metadata.get("app") != str(app):
        raise ValueError("This backup belongs to a different app path")
    original = backup / "MaaEnd.app"
    verify_original(original)
    with tempfile.TemporaryDirectory(prefix=".endplaydesktop-restore-", dir=app.parent) as temporary:
        staged = Path(temporary) / app.name
        copy_app(original, staged)
        swap_app(app, staged)
    return {"status": "restored", "backup": str(backup)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "restore", "build"):
        child = commands.add_parser(name)
        child.add_argument("--app", type=Path, default=DEFAULT_APP)
        if name in ("plan", "apply"):
            child.add_argument("--payload", type=Path)
        if name == "restore":
            child.add_argument("--backup", type=Path, required=True)
        if name == "build":
            child.add_argument("--mxu-source", type=Path, default=ROOT.parent / "MXU")
            child.add_argument("--mxu-binary", type=Path, help="Reuse a binary built from the checked MXU source")
            child.add_argument("--target-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        app = args.app.resolve(strict=True)
        _, directory, version = app_info(app)
        if args.command == "build":
            from .build_patch import build_payload
            result = build_payload(app, args.mxu_source.resolve(), args.mxu_binary, args.target_dir)
        elif args.command == "restore":
            result = restore(app, args.backup.resolve(strict=True))
        else:
            payload = (args.payload or ROOT / ".cache/payloads" / version).resolve()
            if args.command == "plan":
                _, payload_id = load_payload(payload, app)
                changes, filters = resource_changes(directory, ROOT)
                result = {"app": str(app), "version": version, "payload_id": payload_id,
                          "resource_files": [str(p) for p in changes], "changed_controller_filters": filters,
                          "excluded": list(EXCLUDED), "executables": ["MXU", "Go Agent"]}
            else:
                result = apply_patch(app, payload, ROOT, ROOT / "backups/apps")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"EndPlayDesktop: {error}", file=sys.stderr)
        return 1
