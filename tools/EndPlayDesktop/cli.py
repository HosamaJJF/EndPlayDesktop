from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .client import BridgeClient, BridgeError, find_endpoint


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_runtime(install: Path) -> None:
    from maa.library import Library
    from maa.toolkit import Toolkit

    binary = install / "maafw"
    if not binary.is_dir():
        raise FileNotFoundError(f"找不到 MaaFramework 目录: {binary}")
    Library.open(binary)
    if not Toolkit.init_option(install / "debug/EndPlayDesktop"):
        raise RuntimeError("MaaFramework 日志初始化失败")


def run_task(controller: Any, install: Path, entry: str, override: dict) -> bool:
    """使用正式 PC 资源与两个 Agent 执行指定入口，不加载触控或 Mac 键码覆盖层。"""
    from maa.agent_client import AgentClient
    from maa.resource import Resource
    from maa.tasker import Tasker

    processes: list[subprocess.Popen] = []
    clients: list[AgentClient] = []
    tasker = None
    log_dir = install / "debug/EndPlayDesktop"
    log_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Use a desktop kind understood by stock Agents, keeping Win32 registry paths disabled.
    env["PI_CONTROLLER"] = json.dumps({"name": "EndPlayDesktop", "type": "MacOS"})
    env["PI_RESOURCE"] = json.dumps({"name": "官服", "path": [str(install / "resource")]}, ensure_ascii=False)
    env["PATH"] = os.pathsep.join([str(install / "agent"), str(install / "maafw"), env.get("PATH", "")])
    with contextlib.ExitStack() as stack:
        try:
            resource = Resource()
            if not resource.post_bundle(str(install / "resource")).wait().succeeded:
                raise RuntimeError("PC 基础资源装载失败，请先构建 install 目录")
            tasker = Tasker()
            for name in ("go-service", "cpp-algo"):
                executable = install / "agent" / name
                if not executable.is_file():
                    raise FileNotFoundError(f"找不到 Agent: {executable}")
                # macOS 的 UNIX socket 路径上限很短；用官方 loopback TCP 自动分配端口，
                # 避免安装目录或 TMPDIR 较长时在原生 ZeroMQ 层直接终止进程。
                client = AgentClient.create_tcp()
                clients.append(client)
                if not client.bind(resource):
                    raise RuntimeError(f"{name} 无法绑定资源")
                output = stack.enter_context((log_dir / f"{name}.log").open("ab"))
                processes.append(subprocess.Popen([str(executable), client.identifier], cwd=install,
                                                  env=env, stdout=output, stderr=subprocess.STDOUT,
                                                  start_new_session=True))
                if not client.connect():
                    raise RuntimeError(f"{name} 连接失败，详情见 {log_dir}")
                if not client.register_sink(resource, controller, tasker):
                    raise RuntimeError(f"{name} 事件监听器注册失败")
            if not tasker.bind(resource, controller) or not tasker.inited:
                raise RuntimeError("Tasker 初始化失败")
            logging.info("Running PC pipeline: %s", entry)
            job = tasker.post_task(entry, override)
            # 原生 wait 阻塞时 Python 无法及时处理 Ctrl-C；轮询异步状态，
            # 让 finally 能在 Agent 仍存活时取消任务并释放输入。
            while not job.done:
                time.sleep(0.05)
            succeeded = job.succeeded
            logging.info("PC pipeline %s: %s", entry, "succeeded" if succeeded else "failed")
            return succeeded
        finally:
            if tasker is not None and tasker.running:
                tasker.post_stop().wait()
            # 先释放所有按键，再关闭 Agent；停止任务或 Ctrl-C 均走此路径。
            controller.close()
            for client in reversed(clients):
                client.disconnect()
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EndPlayDesktop 专用 MaaEnd 控制器")
    parser.add_argument("--endpoint", type=Path, help="插件生成的私有 endpoint.json")
    parser.add_argument("--install-dir", type=Path, default=Path("/Applications/MaaEnd.app/Contents/MacOS"))
    parser.add_argument("--maatools-address", default="127.0.0.1:1717")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="读取插件状态，不建立自动化输入会话")
    commands.add_parser("sidecar", help="为适配版 MXU 提供私有控制器通道")
    probe = commands.add_parser("probe", help="检查自动化会话内的 Unity 输入更新，不发送按键或鼠标移动")
    probe.add_argument("--seconds", type=float, default=5)
    screenshot = commands.add_parser("screenshot", help="检查组合控制器并保存截图")
    screenshot.add_argument("output", type=Path)
    run = commands.add_parser("run", help="运行已有 PC Pipeline 入口")
    run.add_argument("entry")
    run.add_argument("--override", type=Path, help="可选 Pipeline override JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        endpoint = args.endpoint or find_endpoint()
        if args.command == "sidecar":
            from .controller import EndPlayDesktopDevice
            from .sidecar import main as sidecar_main

            return sidecar_main(EndPlayDesktopDevice(endpoint, args.maatools_address))
        if args.command in ("status", "probe"):
            with BridgeClient(endpoint) as bridge:
                status = bridge.request("status")
                if args.command == "probe":
                    if not 0 < args.seconds <= 60:
                        raise ValueError("probe seconds 必须大于 0 且不超过 60")
                    start = bridge.request("begin")
                    last_count = start["input_update_count"]
                    last_focused = start.get("native_app_active")
                    background_updates = 0
                    last_change = time.monotonic()
                    try:
                        deadline = time.monotonic() + args.seconds
                        while time.monotonic() < deadline:
                            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                            status = bridge.request("status")
                            if not status.get("ready") or not status.get("automation"):
                                raise BridgeError("检查期间插件或自动化会话失效")
                            if status["input_update_count"] != last_count:
                                if status.get("native_app_active") is False and last_focused is False:
                                    background_updates += (status["input_update_count"] - last_count) & 0xffffffff
                                last_count = status["input_update_count"]
                                last_change = time.monotonic()
                            elif time.monotonic() - last_change >= 2:
                                raise BridgeError("Unity 输入更新停滞，当前不能后台操作")
                            last_focused = status.get("native_app_active")
                        if status["input_update_count"] == start["input_update_count"]:
                            raise BridgeError("Unity 输入更新未推进，当前不能后台操作")
                    finally:
                        bridge.request("end")
                    updates = (status["input_update_count"] - start["input_update_count"]) & 0xffffffff
                    status = {**bridge.request("status"), "probe_input_updates": updates,
                              "probe_background_input_updates": background_updates}
                print(json.dumps(status, ensure_ascii=False, indent=2))
                return 0 if status.get("ready") else 1

        load_runtime(args.install_dir)
        from .controller import EndPlayDesktopController

        controller = EndPlayDesktopController(endpoint, args.maatools_address)
        try:
            if not controller.post_connection().wait().succeeded:
                raise BridgeError("组合控制器连接失败")
            if args.command == "screenshot":
                if not controller.post_screencap().wait().succeeded:
                    raise BridgeError("截图失败")
                from PIL import Image
                args.output.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(controller.cached_image[:, :, ::-1]).save(args.output)
                print(args.output.resolve())
                return 0
            override = json.loads(args.override.read_text(encoding="utf-8")) if args.override else {}
            if not isinstance(override, dict):
                raise ValueError("override 必须为 JSON object")
            return 0 if run_task(controller, args.install_dir, args.entry, override) else 1
        finally:
            controller.close()
    except KeyboardInterrupt:
        return 130
    except (BridgeError, OSError, ValueError, RuntimeError, ImportError) as exc:
        logging.error("%s", exc)
        return 1
