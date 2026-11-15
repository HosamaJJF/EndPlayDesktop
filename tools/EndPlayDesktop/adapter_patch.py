"""Install an external controller adapter while retaining the upstream MXU."""
from __future__ import annotations

import plistlib
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .patch import (RECEIPT, app_info, contained, copy_app, digest, executable_identity,
                    original_agent, read_json, resource_changes, sign_app, swap_app,
                    verify_app, verify_original, write_json)

LAUNCHER = "EndPlayDesktopLauncher"
ADAPTER = Path("Contents/Resources/EndPlayDesktop/libEndPlayDesktopController.dylib")
CONFIG = Path("Contents/Resources/EndPlayDesktop/runtime.json")


def sign_upstream(executable: Path) -> None:
    # Changing CFBundleExecutable invalidates the original binary's signed
    # Info.plist slot. Refresh its signature, keeping upstream code, UUID and
    # entitlements. Never substitute a binary built from an older MXU source.
    subprocess.run(["codesign", "--force", "--sign", "-",
                    "--preserve-metadata=identifier,entitlements,flags,runtime", str(executable)], check=True)


def upstream_client(app: Path, receipt: dict, version: str) -> tuple[str, Path | None]:
    info, directory, _ = app_info(app)
    name = info["CFBundleExecutable"]
    if name == LAUNCHER:
        config = read_json(app / CONFIG) if (app / CONFIG).is_file() else {}
        name = receipt.get("upstream_executable") or config.get("upstream_executable", "")
        if not name or Path(name).name != name or name == LAUNCHER or not (directory / name).is_file():
            raise ValueError("找不到原版 MXU，请重新安装官方 MaaEnd 后再应用补丁。")
        return name, None
    # A normal upstream update can retain an old receipt while installing a new
    # executable and version. Never transplant an MXU from a different release.
    if receipt.get("format") not in (1, 2) or receipt.get("maaend_version") != version:
        return name, None
    seen = {app.resolve()}
    while receipt.get("backup"):
        donor = Path(receipt["backup"]) / "MaaEnd.app"
        if not donor.is_dir() or donor.resolve() in seen:
            break
        seen.add(donor.resolve())
        donor_info, donor_directory, donor_version = app_info(donor)
        if donor_version != version:
            break
        if not (donor / RECEIPT).is_file():
            if donor_info["CFBundleExecutable"] != name:
                break
            verify_original(donor)
            return name, donor_directory / name
        receipt = read_json(donor / RECEIPT)
        if receipt.get("format") not in (1, 2):
            break
    raise ValueError("旧补丁替换过 MXU，未找到同版本官方原包备份。请先重新安装当前官方 MaaEnd，再应用新版补丁；任务配置无需删除。")


def apply_adapter_patch(app: Path, payload: Path, runtime: Path, backups: Path,
                        runtime_python: Path | None, manifest: dict, payload_id: str) -> dict:
    info, directory, version = app_info(app)
    existing = read_json(app / RECEIPT) if (app / RECEIPT).exists() else {}
    name, donor = upstream_client(app, existing, version)
    agent = original_agent(app, existing, version)
    changes, filters = resource_changes(directory, runtime, runtime_python, external=True)
    python = runtime_python.absolute() if runtime_python else runtime.resolve() / ".venv/bin/python"
    config = {"format": 1, "python": str(python), "project_dir": str(runtime.resolve()), "upstream_executable": name}
    identity = executable_identity(donor or directory / name)
    if (existing.get("format") == 3 and existing.get("payload_id") == payload_id and not changes
            and existing.get("upstream_identity") == identity and info["CFBundleExecutable"] == LAUNCHER
            and (app / CONFIG).is_file() and read_json(app / CONFIG) == config
            and (app / ADAPTER).is_file() and digest(app / ADAPTER) == manifest["files"]["controller"]["sha256"]
            and executable_identity(directory / LAUNCHER) == executable_identity(contained(payload, manifest["files"]["launcher"]["path"]))):
        verify_app(app)
        return {"status": "already_applied", "version": version, "preserves_upstream_mxu": True}
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
        if donor is not None:
            shutil.copy2(donor, target / name)
        if agent is not None:
            shutil.copy2(agent, target / "agent/go-service")
        (staged / ADAPTER).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(contained(payload, manifest["files"]["controller"]["path"]), staged / ADAPTER)
        shutil.copy2(contained(payload, manifest["files"]["launcher"]["path"]), target / LAUNCHER)
        (target / LAUNCHER).chmod(0o755)
        (staged / "Contents/Info.plist").write_bytes(plistlib.dumps({**info, "CFBundleExecutable": LAUNCHER}))
        write_json(staged / CONFIG, config)
        write_json(staged / RECEIPT, {
            "format": 3, "payload_id": payload_id, "maaend_version": version,
            "backup": str(backup), "runtime": str(runtime.resolve()),
            "upstream_executable": name, "upstream_identity": identity,
        })
        sign_upstream(target / name)
        sign_app(staged, [target / relative for relative, value in changes.items() if value is not None])
        swap_app(app, staged)
    return {"status": "applied", "version": version, "backup": str(backup), "changed_resource_files": len(changes),
            "changed_controller_filters": filters, "preserves_upstream_mxu": True,
            "recovered_mxu": donor is not None, "recovered_agent": agent is not None}
