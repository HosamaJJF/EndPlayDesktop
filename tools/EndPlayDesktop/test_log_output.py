from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from .log_output import GuiLogFormatter


class MessageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.text = ""
        self.style = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag == "br":
            self.text += "\n"
        elif tag == "span":
            self.style = dict(attrs).get("style") or ""

    def handle_data(self, data: str) -> None:
        self.text += data


class GuiLogTests(unittest.TestCase):
    def test_messages_keep_their_text_and_follow_theme_colors(self) -> None:
        text = '游戏 <test> & "quoted"\n下一行'
        for level, color in ((logging.INFO, "info"), (logging.WARNING, "warning"), (logging.ERROR, "error")):
            with self.subTest(level=level):
                record = logging.LogRecord("test", level, __file__, 0, "%s", (text,), None)
                output = GuiLogFormatter().format(record)
                parser = MessageParser()
                parser.feed(output)
                self.assertEqual(parser.text, text)
                self.assertEqual(parser.tags, ["span", "br"])
                self.assertEqual(parser.style, f"color: var(--color-{color})")
                self.assertNotIn("\n", output)
                self.assertNotIn(logging.getLevelName(level) + ":", output)

    def test_error_details_cannot_insert_html_elements(self) -> None:
        text = '</span><img src=x onerror="alert(1)"><script>bad</script>'
        record = logging.LogRecord("test", logging.ERROR, __file__, 0, "%s", (text,), None)
        parser = MessageParser()
        parser.feed(GuiLogFormatter().format(record))
        self.assertEqual(parser.tags, ["span"])
        self.assertEqual(parser.text, text)

    def test_pretask_errors_use_rich_output_and_terminal_errors_stay_plain(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            options = json.dumps({"EndPlayDesktopAppPath": {"Path": str(Path(temporary) / "game<test>.app")}})
            for gui in (False, True):
                command = [sys.executable, "-m", "tools.EndPlayDesktop", "launch-game"]
                if gui:
                    command.append("--gui-log")
                result = subprocess.run(command + [options], cwd=root, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1)
                if gui:
                    self.assertEqual(result.stderr, "")
                    self.assertIn("var(--color-error)", result.stdout)
                    self.assertIn("game&lt;test&gt;.app", result.stdout)
                else:
                    self.assertEqual(result.stdout, "")
                    self.assertIn("ERROR:", result.stderr)


if __name__ == "__main__":
    unittest.main()
