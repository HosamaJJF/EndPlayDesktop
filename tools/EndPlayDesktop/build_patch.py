"""Build version-matched patch executables from the checked upstream sources."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .patch import ROOT, app_info, digest, read_json, write_json


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def commit(source: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()


def apply_source_patch(source: Path, patch: Path) -> None:
    applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=source,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not applied:
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", "--intent-to-add", str(patch), cwd=source)


def prepare_mxu(source: Path, versions: dict) -> None:
    pin = versions["mxu"]
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--branch", pin["tag"], "--depth", "1", pin["repository"], str(source), cwd=ROOT)
    native = source / "src-tauri/src/commands/endplaydesktop.rs"
    expected = ROOT / "patches/mxu/controller.rs"
    if native.exists() and native.read_bytes() != expected.read_bytes():
        raise ValueError("MXU driver has local edits; preserve them and update the repository patch first")
    apply_source_patch(source, ROOT / "patches/mxu.patch")
    if not native.exists():
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


def prepare_agent(version: str, versions: dict) -> Path:
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.\-+]*", version):
        raise ValueError("Unsupported release tag")
    source = ROOT / ".cache/sources/MaaEnd" / version
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", version,
            versions["maaend"]["repository"], str(source), cwd=ROOT)
        run("git", "sparse-checkout", "set", "agent/go-service", cwd=source)
    apply_source_patch(source, ROOT / "patches/maaend-agent.patch")
    return source


def build_payload(app: Path, mxu_source: Path, mxu_binary: Path | None = None,
                  target_dir: Path | None = None) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Build on an Apple Silicon Mac")
    versions = read_json(ROOT / "patches/versions.json")
    _, _, version = app_info(app)
    prepare_mxu(mxu_source, versions)
    agent_source = prepare_agent(version, versions)
    binary = mxu_binary.resolve(strict=True) if mxu_binary else build_mxu(
        mxu_source, (target_dir or mxu_source / "target").resolve())
    cache = ROOT / ".cache/payloads"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / version
    # Never damage an existing payload if building or validation fails.
    with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as temporary:
        payload = Path(temporary) / version
        payload.mkdir()
        shutil.copy2(binary, payload / "mxu")
        env = {**os.environ, "GOOS": "darwin", "GOARCH": "arm64", "CGO_ENABLED": "0"}
        env.setdefault("GOCACHE", str(ROOT / ".cache/go-build"))
        env.setdefault("GOMODCACHE", str(ROOT / ".cache/go-mod"))
        run("go", "test", "-mod=readonly", "./pkg/pienv", cwd=agent_source / "agent/go-service", env=env)
        run("go", "build", "-mod=readonly", "-trimpath", f"-ldflags=-X main.Version={version}",
            "-o", str(payload / "go-service"), ".", cwd=agent_source / "agent/go-service", env=env)
        for name in ("mxu", "go-service"):
            run("codesign", "--force", "--sign", "-", str(payload / name), cwd=ROOT)
            arch = subprocess.check_output(["lipo", "-archs", str(payload / name)], text=True).strip()
            if arch != "arm64":
                raise ValueError(f"Unexpected executable architecture: {name} ({arch})")
        write_json(payload / "manifest.json", {
            "format": 1, "maaend_version": version, "maaend_commit": commit(agent_source),
            "mxu_commit": commit(mxu_source), "architecture": "arm64",
            "files": {name: {"path": name, "sha256": digest(payload / name)} for name in ("mxu", "go-service")},
        })
        if destination.exists():
            # A payload is a reproducible build artifact, never app/user data.
            shutil.rmtree(destination)
        payload.rename(destination)
    return {"status": "built", "payload": str(destination), "maaend_version": version,
            "maaend_commit": commit(agent_source), "mxu_commit": commit(mxu_source)}
