"""Pass through to stock Agents using the desktop controller kind they support."""
from __future__ import annotations

import json
import os


def agent_environment(source: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in source.items()
           if key not in ("DYLD_INSERT_LIBRARIES", "ENDPLAYDESKTOP_CONFIG", "ENDPLAYDESKTOP_ADAPTER_LOADED")
           and not key.startswith("_PYI")}
    controller = json.loads(env.get("PI_CONTROLLER", "{}"))
    if controller.get("name") == "EndPlayDesktop" and controller.get("type") == "PlayCover":
        if source.get("ENDPLAYDESKTOP_ADAPTER_LOADED") != "1":
            raise ValueError("EndPlayDesktop 控制器适配层未加载，请重新应用补丁，并通过 MaaEnd.app 启动。")
        controller = {**controller, "type": "MacOS"}
        controller.pop("playcover", None)
        env["PI_CONTROLLER"] = json.dumps(controller, ensure_ascii=False, separators=(",", ":"))
    return env


def exec_agent(arguments: list[str]) -> None:
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if not arguments:
        raise ValueError("Missing upstream Agent command")
    os.execvpe(arguments[0], arguments, agent_environment(dict(os.environ)))
