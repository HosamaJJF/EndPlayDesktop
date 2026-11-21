"""Patch an existing MaaEnd.app while preserving its identity and task settings."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import plistlib
import shutil
import struct
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
PLAYCOVER_LIFECYCLE = ("LaunchGamePlayCover", "CloseGamePlayCover")
LEGACY_LIFECYCLE_TASKS = Path("tasks/EndPlayDesktop.json")
LEGACY_LIFECYCLE_PIPELINE = Path("resource_endplaydesktop/pipeline/lifecycle.json")
RECEIPT = Path("Contents/Resources/EndPlayDesktop/receipt.json")
DEFAULT_APP = Path("/Applications/MaaEnd.app")


class MXUReplacementRequired(ValueError):
    def __init__(self, app: Path, manifest: dict):
        self.app = app
        self.mxu_version = manifest.get("mxu_version") or manifest.get("mxu_commit", "未记录版本的构建")
        super().__init__(
            f"此补丁将把 MaaEnd 自带的 MXU 替换为 {self.mxu_version}，可能失去上游新版功能与修复。"
            "确认接受替换后，使用 --replace-mxu 重试；保留上游 MXU 请取消应用补丁。"
        )


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def executable_identity(path: Path) -> str:
    # Re-signing the app changes its executable's signature and raw hash, but
    # preserves the linker's LC_UUID build identifier. verify_app checks integrity.
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) == 32 and header[:4] == b"\xcf\xfa\xed\xfe":
            commands, size = struct.unpack_from("<II", header, 16)
            end = 32 + size
            for _ in range(commands):
                offset = stream.tell()
                raw = stream.read(8)
                if len(raw) != 8:
                    break
                command, length = struct.unpack("<II", raw)
                if length < 8 or offset + length > end:
                    break
                if command == 0x1B and length == 24:  # LC_UUID
                    uuid = stream.read(16)
                    if len(uuid) == 16:
                        return "macho:" + uuid.hex()
                stream.seek(offset + length)
    return "sha256:" + digest(path)


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


def update_filters(value: object, windows: set[str], playcover: set[str],
                   blocked: bool = False, lifecycle: bool = False) -> int:
    changed = 0
    if isinstance(value, dict):
        blocked = blocked or any(value.get(key) in EXCLUDED for key in ("name", "entry"))
        lifecycle = lifecycle or any(value.get(key) in PLAYCOVER_LIFECYCLE for key in ("name", "entry"))
        supported = windows | playcover if lifecycle else windows
        for key, item in value.items():
            if key == "controller" and isinstance(item, list) and all(isinstance(name, str) for name in item):
                updated = list(item)
                if blocked:
                    updated = [name for name in item if name != CONTROLLER]
                elif supported.intersection(item) and CONTROLLER not in item:
                    updated.append(CONTROLLER)
                if updated != item:
                    value[key] = updated
                    changed += 1
            else:
                child_blocked = blocked or any(key.startswith(name) for name in EXCLUDED)
                child_lifecycle = lifecycle or any(key.startswith(name) for name in PLAYCOVER_LIFECYCLE)
                changed += update_filters(item, windows, playcover, child_blocked, child_lifecycle)
    elif isinstance(value, list):
        changed += sum(update_filters(item, windows, playcover, blocked, lifecycle) for item in value)
    return changed


def resource_changes(directory: Path, runtime: Path, runtime_python: Path | None = None,
                     *, external: bool = False) -> tuple[dict[Path, dict | None], int]:
    directory = directory.resolve()
    runtime = runtime.resolve()
    python = runtime_python.absolute() if runtime_python else runtime / ".venv/bin/python"
    if not python.is_file() or not (runtime / "tools/EndPlayDesktop/sidecar.py").is_file():
        raise ValueError("Missing EndPlayDesktop runtime; run uv sync in its repository first")
    source = documents(directory)
    interface_path = directory / "interface.json"
    interface = source[interface_path]
    windows = {c["name"] for c in interface["controller"] if c.get("type") == "Win32"}
    playcover = {c["name"] for c in interface["controller"] if c.get("type") == "PlayCover"}
    if not windows:
        raise ValueError("No Windows controller definitions found; review this MaaEnd version")
    controller = {
        "name": CONTROLLER, "type": CONTROLLER, "display_short_side": 720,
        "endplaydesktop": {"python": str(python), "project_dir": str(runtime)},
    }
    if external:
        controller = {"name": CONTROLLER, "type": "PlayCover", "display_short_side": 720,
                      "playcover": {"uuid": "maa.endplaydesktop"}}
    changes = {}
    filters = 0
    for path, original in source.items():
        if path.relative_to(directory) == LEGACY_LIFECYCLE_TASKS:
            continue
        updated = copy.deepcopy(original)
        filters += update_filters(updated, windows, playcover)
        if path == interface_path:
            if "import" in updated:
                updated["import"] = [item for item in updated["import"]
                                     if item != LEGACY_LIFECYCLE_TASKS.as_posix()]
            existing = [c for c in updated["controller"] if c["name"] == CONTROLLER]
            if len(existing) > 1:
                raise ValueError("Duplicate EndPlayDesktop controller definitions")
            if existing and not (existing[0].get("type") == CONTROLLER or (
                    external and existing[0].get("type") == "PlayCover" and
                    existing[0].get("playcover", {}).get("uuid") == "maa.endplaydesktop")):
                raise ValueError("EndPlayDesktop name is occupied by another controller type")
            if existing:
                updated["controller"][updated["controller"].index(existing[0])] = controller
            else:
                index = next((i + 1 for i, c in enumerate(updated["controller"]) if c.get("type") == "PlayCover"), len(updated["controller"]))
                updated["controller"].insert(index, controller)
            if external and updated.get("agent"):
                def wrap_agent(agent):
                    original = copy.deepcopy(agent.get("endplaydesktop_original", agent))
                    return {**original, "child_exec": str(python), "child_args": [
                        "-m", "tools.EndPlayDesktop", "agent-exec", "--", original["child_exec"],
                        *original.get("child_args", [])], "endplaydesktop_original": original}
                agents = updated["agent"]
                updated["agent"] = [wrap_agent(agent) for agent in agents] if isinstance(agents, list) else wrap_agent(agents)
        if updated != original:
            changes[path.relative_to(directory)] = updated
    # Remove only the two files generated by older patches. Upstream now owns
    # the lifecycle definitions and the base resource already contains StopApp.
    for relative in (LEGACY_LIFECYCLE_TASKS, LEGACY_LIFECYCLE_PIPELINE):
        if contained(directory, relative).is_file():
            changes[relative] = None
    return changes, filters


def load_payload(payload: Path) -> tuple[dict, str]:
    manifest = read_json(payload / "manifest.json")
    if manifest.get("format") not in (2, 3, 4):
        raise ValueError("Unsupported patch payload format; rebuild the controller payload")
    if manifest.get("architecture") != "arm64":
        raise ValueError("Only the Apple Silicon payload is supported")
    expected = {2: {"mxu"}, 3: {"controller", "launcher"}, 4: {"controller"}}[manifest["format"]]
    if set(manifest["files"]) != expected:
        raise ValueError("Unexpected patch payload files; upstream executables must be preserved")
    for name in manifest["files"]:
        if digest(contained(payload, manifest["files"][name]["path"])) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Corrupt patch payload: {name}")
    return manifest, digest(payload / "manifest.json")


def check_mxu_replacement(app: Path, payload: Path, manifest: dict | None = None) -> None:
    """Require consent whenever applying would replace a different MXU build."""
    if manifest is None:
        manifest, _ = load_payload(payload)
    if manifest["format"] in (3, 4):
        return
    info, directory, _ = app_info(app)
    if executable_identity(directory / info["CFBundleExecutable"]) != executable_identity(
            contained(payload, manifest["files"]["mxu"]["path"])):
        raise MXUReplacementRequired(app, manifest)


def original_agent(app: Path, receipt: dict, version: str) -> Path | None:
    """Recover an Agent overwritten by v1 patches, never from another release."""
    if not receipt or receipt.get("format") in (2, 3, 4):
        return None
    if receipt.get("format") != 1:
        raise ValueError("Unsupported EndPlayDesktop receipt format")
    seen = {app.resolve()}
    while receipt.get("backup"):
        donor = Path(receipt["backup"]) / "MaaEnd.app"
        if not donor.is_dir() or donor.resolve() in seen:
            break
        seen.add(donor.resolve())
        _, directory, donor_version = app_info(donor)
        if donor_version != version:
            break
        donor_receipt = donor / RECEIPT
        if not donor_receipt.exists():
            verify_original(donor)
            agent = directory / "agent/go-service"
            if agent.is_file():
                return agent
            break
        receipt = read_json(donor_receipt)
        if receipt.get("format") != 1:
            break
    raise ValueError(
        "旧版补丁曾替换 Go Agent，未找到同版本的未修改备份。"
        "请重新安装当前版本的官方 MaaEnd.app，再应用此补丁；任务配置无需删除。"
    )


def running(app: Path) -> bool:
    info, directory, _ = app_info(app)
    names = {info["CFBundleExecutable"]}
    if (app / RECEIPT).is_file():
        original = read_json(app / RECEIPT).get("upstream_executable")
        if original:
            names.add(original)
    executables = {(directory / name).resolve() for name in names}
    output = subprocess.check_output(["ps", "-axo", "comm="], text=True)
    return any(Path(line.strip()).resolve() in executables for line in output.splitlines() if line.strip())


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
    # MaaFramework creates configuration and debug records at runtime without the
    # nested signatures macOS requires below Contents/MacOS. Refresh only their
    # metadata, preserving contents and never re-signing Mach-O binaries.
    resources = list(resources)
    macho = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
             b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}
    for folder in ("config", "debug"):
        generated = app / "Contents/MacOS" / folder
        if generated.is_symlink():
            raise ValueError(f"Cannot sign external runtime directory: {folder}")
        for path in generated.rglob("*"):
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    if stream.read(4) not in macho:
                        resources.append(path)
    for path in dict.fromkeys(resources):
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


def apply_patch(app: Path, payload: Path, runtime: Path, backups: Path,
                runtime_python: Path | None = None, *, replace_mxu: bool = False) -> dict:
    if running(app):
        raise ValueError("Quit MaaEnd before applying the patch")
    manifest, payload_id = load_payload(payload)
    if manifest["format"] in (3, 4):
        from .adapter_patch import apply_adapter_patch
        return apply_adapter_patch(app, payload, runtime, backups, runtime_python, manifest, payload_id)
    if not replace_mxu:
        check_mxu_replacement(app, payload, manifest)
    info, directory, version = app_info(app)
    changes, filters = resource_changes(directory, runtime, runtime_python)
    existing = read_json(app / RECEIPT) if (app / RECEIPT).exists() else {}
    agent = original_agent(app, existing, version)
    if (existing.get("format") == 2 and existing.get("payload_id") == payload_id
            and existing.get("maaend_version") == version and not changes
            and executable_identity(directory / info["CFBundleExecutable"])
            == executable_identity(contained(payload, manifest["files"]["mxu"]["path"]))):
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
            if value is None:
                contained(target, relative).unlink()
            else:
                write_json(target / relative, value)
        destination = target / info["CFBundleExecutable"]
        shutil.copy2(contained(payload, manifest["files"]["mxu"]["path"]), destination)
        destination.chmod(0o755)
        if agent is not None:
            shutil.copy2(agent, target / "agent/go-service")
        write_json(staged / RECEIPT, {
            "format": 2, "payload_id": payload_id, "maaend_version": version,
            "backup": str(backup), "runtime": str(runtime),
            "mxu_version": manifest.get("mxu_version"), "mxu_commit": manifest.get("mxu_commit"),
        })
        sign_app(staged, [target / relative for relative, value in changes.items() if value is not None])
        swap_app(app, staged)
    return {"status": "applied", "version": version, "changed_resource_files": len(changes),
            "changed_controller_filters": filters, "backup": str(backup), "recovered_agent": agent is not None}


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
        if name == "apply":
            child.add_argument("--replace-mxu", action="store_true",
                               help="Explicitly allow replacing the target MXU with the patch's bundled build")
        if name == "restore":
            child.add_argument("--backup", type=Path, required=True)
        if name == "build":
            child.add_argument("--target-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        app = args.app.resolve(strict=True)
        _, directory, version = app_info(app)
        if args.command == "build":
            from .build_patch import build_payload
            result = build_payload(app, args.target_dir)
        elif args.command == "restore":
            result = restore(app, args.backup.resolve(strict=True))
        else:
            payload = (args.payload or ROOT / ".cache/payloads/desktop").resolve()
            if args.command == "plan":
                manifest, payload_id = load_payload(payload)
                changes, filters = resource_changes(directory, ROOT, external=manifest["format"] in (3, 4))
                receipt = read_json(app / RECEIPT) if (app / RECEIPT).exists() else {}
                agent = original_agent(app, receipt, version)
                result = {"app": str(app), "version": version, "payload_id": payload_id,
                          "resource_files": [str(p) for p in changes], "changed_controller_filters": filters,
                          "excluded": list(EXCLUDED), "executables": {2: ["MXU"], 3: ["EndPlayDesktopLauncher", "controller adapter"], 4: ["controller adapter"]}[manifest["format"]],
                          "recover_agent_from": str(agent) if agent else None,
                          "mxu_version": manifest.get("mxu_version"), "mxu_commit": manifest.get("mxu_commit")}
                if manifest["format"] in (3, 4):
                    from .adapter_patch import upstream_client
                    _, donor = upstream_client(app, receipt, version)
                    result.update(recover_mxu_from=str(donor) if donor else None,
                                  preserves_upstream_mxu=True, mxu_replacement_required=False)
                else:
                    try:
                        check_mxu_replacement(app, payload, manifest)
                        result["mxu_replacement_required"] = False
                    except MXUReplacementRequired:
                        result["mxu_replacement_required"] = True
            else:
                result = apply_patch(app, payload, ROOT, ROOT / "backups/apps", replace_mxu=args.replace_mxu)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"EndPlayDesktop: {error}", file=sys.stderr)
        return 1
