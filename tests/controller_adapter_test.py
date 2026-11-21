"""Exercise the linked adapter and child lifetime without a launcher or game."""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.EndPlayDesktop.macho import add_adapter_dependency


def main():
    adapter, client, framework = map(Path, sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix="endplaydesktop adapter ") as temporary:
        root = Path(temporary)
        app = root / "MaaEnd.app/Contents"
        resources = app / "Resources/EndPlayDesktop"
        binary = app / "MacOS"
        resources.mkdir(parents=True)
        binary.mkdir()
        (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "upstream-client",
            "CFBundleIdentifier": "test.endplaydesktop.adapter", "CFBundlePackageType": "APPL"}))
        shutil.copy2(client, binary / "upstream-client")
        add_adapter_dependency(binary / "upstream-client")
        subprocess.run(["codesign", "--force", "--sign", "-", str(binary / "upstream-client")], check=True)
        shutil.copy2(adapter, resources / adapter.name)
        project = root / "runtime project"
        module = project / "tools/EndPlayDesktop"
        module.mkdir(parents=True)
        (module.parent / "__init__.py").touch()
        (module / "__init__.py").touch()
        trace = root / "operations.jsonl"
        (module / "__main__.py").write_text('''import json, os, struct, sys
assert "DYLD_INSERT_LIBRARIES" not in os.environ
assert sys.argv[1:] == ["--maatools-address", "127.0.0.1:1718", "sidecar"]
source, output = sys.stdin.buffer, sys.stdout.buffer
with open(os.environ["EPD_TEST_TRACE"], "a") as trace:
    while True:
        header = source.read(4)
        if not header:
            trace.write(json.dumps({"op":"eof"}) + "\\n")
            break
        size = struct.unpack("!I", header)[0]
        request = json.loads(source.read(size))
        trace.write(json.dumps(request) + "\\n")
        trace.flush()
        payload = b"test image" if request["op"] == "screencap" else b""
        body = json.dumps({"ok":True,"result":True,"payload_size":len(payload)}).encode()
        output.write(struct.pack("!I", len(body)) + body + payload)
        output.flush()
''')
        (resources / "runtime.json").write_text(json.dumps({
            "upstream_executable": "upstream-client", "python": sys.executable, "project_dir": str(project),
        }))
        env = {key: value for key, value in os.environ.items() if not key.startswith("DYLD_")}
        env["EPD_TEST_TRACE"] = str(trace)
        subprocess.run([str(binary / "upstream-client"), str(framework), "argument with spaces"],
                       cwd=root, env=env, check=True, timeout=20)
        operations = [json.loads(line) for line in trace.read_text().splitlines()]
        assert [item["op"] for item in operations] == ["connect", "connected", "screencap", "touch_down", "touch_move",
            "touch_up", "key_down", "key_up", "scroll", "relative_move", "inactive", "stop_app", "eof"], operations
        assert operations[3]["args"] == [1, 100, 200, 0]
        assert operations[9]["args"] == [25, -10]


if __name__ == "__main__":
    main()
