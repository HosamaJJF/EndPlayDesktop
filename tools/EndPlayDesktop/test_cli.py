from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from .cli import main, run_task


class LaunchCommandTests(unittest.TestCase):
    def test_launch_does_not_require_an_endpoint_before_opening_game(self) -> None:
        with patch("tools.EndPlayDesktop.lifecycle.launch_game") as launch, \
                patch("tools.EndPlayDesktop.cli.find_endpoint", side_effect=AssertionError("too early")):
            options = json.dumps({"EndPlayDesktopAppPath": {"Path": "/Games/Endfield.app"}})
            self.assertEqual(main(["launch-game", options]), 0)
        launch.assert_called_once_with("/Games/Endfield.app", delay=10, timeout=90)


    def test_task_delay_and_cli_override_do_not_pass_an_address(self) -> None:
        options = json.dumps({"EndPlayDesktopLaunchDelay": {"Seconds": "12.5"}})
        with patch("tools.EndPlayDesktop.lifecycle.launch_game") as launch:
            self.assertEqual(main(["launch-game", options]), 0)
            launch.assert_called_once_with("", delay=12.5, timeout=90)
            launch.reset_mock()
            self.assertEqual(main(["launch-game", options, "--delay", "0"]), 0)
            launch.assert_called_once_with("", delay=0, timeout=90)

    def test_invalid_delay_option_is_rejected(self) -> None:
        with patch("tools.EndPlayDesktop.lifecycle.launch_game") as launch:
            for value in ([], {"Seconds": []}, {"Seconds": True}, {"Seconds": "abc"}):
                self.assertEqual(main(["launch-game", json.dumps({"EndPlayDesktopLaunchDelay": value})]), 1)
            launch.assert_not_called()


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.install = Path(directory) / ("long-install-path-" * 8)
        (self.install / "agent").mkdir(parents=True)
        for name in ("go-service", "cpp-algo"):
            (self.install / "agent" / name).touch()
        self.controller = Mock()
        self.resource = Mock()
        self.resource.post_bundle.return_value.wait.return_value.succeeded = True
        self.tasker = Mock()
        self.tasker.running = False
        self.tasker.post_task.return_value.done = True
        self.tasker.post_task.return_value.succeeded = True
        self.clients = [Mock(identifier="50001"), Mock(identifier="50002")]
        self.processes = [Mock(), Mock()]
        for process in self.processes:
            process.poll.return_value = None
        self.factory = self.stack.enter_context(patch("maa.agent_client.AgentClient.create_tcp", side_effect=self.clients))
        self.stack.enter_context(patch("maa.resource.Resource", return_value=self.resource))
        self.stack.enter_context(patch("maa.tasker.Tasker", return_value=self.tasker))
        self.popen = self.stack.enter_context(patch("tools.EndPlayDesktop.cli.subprocess.Popen", side_effect=self.processes))

    def test_long_install_path_uses_tcp_and_registers_both_agent_sinks(self) -> None:
        self.assertGreater(len(str(self.install)), 104)
        self.assertTrue(run_task(self.controller, self.install, "SceneEnterMenuList", {}))
        self.assertEqual(self.factory.call_count, 2)
        for client, process, call in zip(self.clients, self.processes, self.popen.call_args_list):
            self.assertEqual(call.args[0][1], client.identifier)
            self.assertEqual(call.kwargs["cwd"], self.install)
            self.assertEqual(json.loads(call.kwargs["env"]["PI_CONTROLLER"]),
                             {"name": "EndPlayDesktop", "type": "MacOS"})
            self.assertTrue(call.kwargs["start_new_session"])
            client.register_sink.assert_called_once_with(self.resource, self.controller, self.tasker)
            client.disconnect.assert_called_once()
            process.terminate.assert_called_once()
        self.tasker.post_task.assert_called_once_with("SceneEnterMenuList", {})
        self.tasker.post_task.return_value.wait.assert_not_called()
        self.tasker.post_stop.assert_not_called()
        self.controller.close.assert_called_once()

    def test_second_agent_failure_stops_first_and_releases_controller(self) -> None:
        self.clients[1].connect.return_value = False
        with self.assertRaisesRegex(RuntimeError, "cpp-algo 连接失败"):
            run_task(self.controller, self.install, "SceneEnterMenuList", {})
        self.tasker.post_task.assert_not_called()
        self.controller.close.assert_called_once()
        for client, process in zip(self.clients, self.processes):
            client.disconnect.assert_called_once()
            process.terminate.assert_called_once()

    def test_ctrl_c_stops_task_before_disconnecting_agents_and_releases_input(self) -> None:
        self.tasker.post_task.return_value.done = False
        self.tasker.running = True
        with patch("tools.EndPlayDesktop.cli.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                run_task(self.controller, self.install, "AutoCollectRoute6Start", {})
        self.tasker.post_stop.assert_called_once()
        self.tasker.post_stop.return_value.wait.assert_called_once()
        self.controller.close.assert_called_once()
        for client, process in zip(self.clients, self.processes):
            client.disconnect.assert_called_once()
            process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
