"""Build the reusable MXU controller patch; use the target app's own Agents."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from .patch import ROOT, app_info, digest, read_json, write_json


# Previously distributed driver, accepted only for an exact, unedited upgrade.
LEGACY_DRIVERS = {"1c1ac24960a4e41dd213f04f01a894c6a405b27b56ba7c0604cdc11a3bc332d6"}


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def commit(source: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()


def source_patch_applied(source: Path, patch: Path) -> bool:
    return subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=source,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def apply_source_patch(source: Path, patch: Path) -> None:
    if not source_patch_applied(source, patch):
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", "--intent-to-add", str(patch), cwd=source)


def prepare_mxu(source: Path, versions: dict) -> None:
    pin = versions["mxu"]
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--branch", pin["tag"], "--depth", "1", pin["repository"], str(source), cwd=ROOT)
    native = source / "src-tauri/src/commands/endplaydesktop.rs"
    expected = ROOT / "patches/mxu/controller.rs"
    if native.exists() and native.read_bytes() != expected.read_bytes() and digest(native) not in LEGACY_DRIVERS:
        raise ValueError("MXU driver has local edits; preserve them and update the repository patch first")
    lifecycle = ROOT / "patches/mxu-lifecycle.patch"
    # The lifecycle layer extends imports created by the base patch, so its
    # presence makes a reverse check of the base patch alone inconclusive.
    if not source_patch_applied(source, lifecycle):
        apply_source_patch(source, ROOT / "patches/mxu.patch")
    apply_source_patch(source, lifecycle)
    if not native.exists() or native.read_bytes() != expected.read_bytes():
        shutil.copy2(expected, native)


def build_mxu(source: Path, target: Path) -> Path:
    run("pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--registry=https://registry.npmjs.org", cwd=source)
    run("node", "node_modules/typescript/bin/tsc", cwd=source)
    run("node", "node_modules/vite/bin/vite.js", "build", cwd=source)
    target.mkdir(parents=True, exist_ok=True)
    config = target / "endplaydesktop-build.json"
    write_json(config, {"build": {"beforeBuildCommand": None}})
    run("cargo", "tauri", "build", "--no-bundle", "--ci", "--config", str(config),
        cwd=source, env={**os.environ, "CARGO_TARGET_DIR": str(target)})
    return target / "release/mxu"


def build_payload(app: Path, mxu_source: Path, mxu_binary: Path | None = None,
                  target_dir: Path | None = None) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Build on an Apple Silicon Mac")
    versions = read_json(ROOT / "patches/versions.json")
    _, _, version = app_info(app)
    prepare_mxu(mxu_source, versions)
    binary = mxu_binary.resolve(strict=True) if mxu_binary else build_mxu(
        mxu_source, (target_dir or mxu_source / "target").resolve())
    cache = ROOT / ".cache/payloads"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / "desktop"
    # Never damage an existing payload if building or validation fails.
    with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as temporary:
        payload = Path(temporary) / "desktop"
        payload.mkdir()
        shutil.copy2(binary, payload / "mxu")
        run("codesign", "--force", "--sign", "-", str(payload / "mxu"), cwd=ROOT)
        arch = subprocess.check_output(["lipo", "-archs", str(payload / "mxu")], text=True).strip()
        if arch != "arm64":
            raise ValueError(f"Unexpected executable architecture: mxu ({arch})")
        write_json(payload / "manifest.json", {
            "format": 2, "tested_maaend_version": version,
            "mxu_commit": commit(mxu_source), "architecture": "arm64",
            "files": {"mxu": {"path": "mxu", "sha256": digest(payload / "mxu")}},
        })
        if destination.exists():
            # A payload is a reproducible build artifact, never app/user data.
            shutil.rmtree(destination)
        payload.rename(destination)
    return {"status": "built", "payload": str(destination), "tested_maaend_version": version,
            "mxu_commit": commit(mxu_source)}
