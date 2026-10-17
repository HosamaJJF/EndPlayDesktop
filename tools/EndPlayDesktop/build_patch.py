"""Build version-matched patch executables from the checked upstream sources."""
from __future__ import annotations

import os
import platform
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from .patch import ROOT, RECEIPT, app_info, digest, read_json, write_json


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def commit(source: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()


def client_content_hash(binary: Path) -> str:
    """Hash Mach-O section contents, ignoring bundle-specific signature data."""
    import hashlib

    data = binary.read_bytes()
    if len(data) < 32 or struct.unpack_from("<II", data) != (0xFEEDFACF, 0x0100000C):
        raise ValueError("Expected a thin arm64 MXU executable")
    result = hashlib.sha256()
    offset = 32
    count, commands_size = struct.unpack_from("<II", data, 16)
    if 32 + commands_size > len(data) or count > commands_size // 8:
        raise ValueError("Invalid Mach-O command table")
    for _ in range(count):
        if offset + 8 > 32 + commands_size:
            raise ValueError("Invalid Mach-O command boundary")
        command, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > 32 + commands_size:
            raise ValueError("Invalid Mach-O load command")
        if command == 0x19:  # LC_SEGMENT_64, followed by section_64 entries.
            if size < 72:
                raise ValueError("Invalid Mach-O segment")
            sections = struct.unpack_from("<I", data, offset + 64)[0]
            if 72 + sections * 80 > size:
                raise ValueError("Invalid Mach-O section table")
            for index in range(sections):
                section = offset + 72 + index * 80
                length, position = struct.unpack_from("<QI", data, section + 40)
                kind = struct.unpack_from("<I", data, section + 64)[0] & 0xFF
                if position and length and kind not in (1, 12, 18):  # Zero-filled sections have no file data.
                    if position + length > len(data):
                        raise ValueError("Invalid Mach-O section range")
                    result.update(data[section:section + 32])
                    result.update(struct.pack("<Q", length))
                    result.update(data[position:position + length])
        offset += size
    return result.hexdigest()


def apply_source_patch(source: Path, patch: Path) -> None:
    applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=source,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not applied:
        run("git", "apply", "--check", str(patch), cwd=source)
        run("git", "apply", "--intent-to-add", str(patch), cwd=source)


def require_controller_patch_only(source: Path, patch: Path) -> None:
    def normalized(diff: str) -> str:
        # Object-id abbreviations and upstream line offsets may differ without
        # changing the patch. All changed code and its context must still match.
        return "\n".join(re.sub(r"^@@ -[0-9,]+ \+[0-9,]+ @@", "@@", line)
                         for line in diff.splitlines() if not line.startswith("index "))

    actual = subprocess.check_output(["git", "diff", "--no-ext-diff", "--binary", "HEAD"], cwd=source, text=True)
    if normalized(actual) != normalized(patch.read_text(encoding="utf-8")):
        raise ValueError(f"{source.name} has changes beyond the controller patch; preserve them and review the source")


def prepare_mxu(source: Path, versions: dict) -> None:
    pin = versions["mxu"]
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--branch", pin["tag"], "--depth", "1", pin["repository"], str(source), cwd=ROOT)
    if commit(source) != pin["commit"]:
        raise ValueError(f"MXU source must be pinned to {pin['commit']}; keep other checkouts unchanged")
    native = source / "src-tauri/src/commands/endplaydesktop.rs"
    expected = ROOT / "patches/mxu/controller.rs"
    if native.exists() and native.read_bytes() != expected.read_bytes():
        raise ValueError("MXU driver has local edits; preserve them and update the repository patch first")
    apply_source_patch(source, ROOT / "patches/mxu.patch")
    require_controller_patch_only(source, ROOT / "patches/mxu.patch")
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


def prepare_agent(app: Path, version: str, versions: dict) -> Path:
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.\-+]*", version):
        raise ValueError("Unsupported release tag")
    source = ROOT / ".cache/sources/MaaEnd" / version
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", "--branch", version,
            versions["maaend"]["repository"], str(source), cwd=ROOT)
        run("git", "sparse-checkout", "set", "agent/go-service", cwd=source)
    info, directory, _ = app_info(app)
    original = directory / "agent/go-service"
    receipt = app / RECEIPT
    if receipt.exists():
        backup = Path(read_json(receipt)["backup"])
        original = backup / "MaaEnd.app/Contents/MacOS/agent/go-service"
    build_info = subprocess.check_output(["go", "version", "-m", str(original)], text=True)
    revision = re.search(r"vcs.revision=([0-9a-f]{40})", build_info)
    expected = versions["maaend"]["tested"].get(version)
    actual = commit(source)
    if (revision and revision.group(1) != actual) or (expected and expected != actual):
        raise ValueError("MaaEnd source revision differs from the packaged Go Agent")
    if not revision:
        raise ValueError("Cannot identify the packaged Go Agent source revision")
    apply_source_patch(source, ROOT / "patches/maaend-agent.patch")
    require_controller_patch_only(source, ROOT / "patches/maaend-agent.patch")
    return source


def build_payload(app: Path, mxu_source: Path, mxu_binary: Path | None = None,
                  target_dir: Path | None = None) -> dict:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Build on an Apple Silicon Mac")
    versions = read_json(ROOT / "patches/versions.json")
    info, directory, version = app_info(app)
    original_client = directory / info["CFBundleExecutable"]
    if (app / RECEIPT).exists():
        original_client = Path(read_json(app / RECEIPT)["backup"]) / "MaaEnd.app/Contents/MacOS" / info["CFBundleExecutable"]
    if client_content_hash(original_client) not in versions["mxu"]["packaged_content_hashes"]:
        raise ValueError("The packaged MXU client has changed; rebase the controller patch before building, rather than replacing it with an older client")
    prepare_mxu(mxu_source, versions)
    agent_source = prepare_agent(app, version, versions)
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
        receipt = read_json(app / RECEIPT) if (app / RECEIPT).exists() else None
        base = receipt["base"] if receipt else {
            "mxu": digest(directory / info["CFBundleExecutable"]),
            "go-service": digest(directory / "agent/go-service"),
        }
        write_json(payload / "manifest.json", {
            "format": 1, "maaend_version": version, "maaend_commit": commit(agent_source),
            "mxu_commit": commit(mxu_source), "architecture": "arm64", "base": base,
            "files": {name: {"path": name, "sha256": digest(payload / name)} for name in ("mxu", "go-service")},
        })
        if destination.exists():
            # A payload is a reproducible build artifact, never app/user data.
            shutil.rmtree(destination)
        payload.rename(destination)
    return {"status": "built", "payload": str(destination), "maaend_version": version,
            "maaend_commit": commit(agent_source), "mxu_commit": commit(mxu_source)}
