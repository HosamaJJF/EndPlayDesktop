"""Native macOS interface for the self-contained patch application."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from .desktop import Distribution, SUPPORT, restore_backup
from .patch import DEFAULT_APP, app_info, apply_patch, read_json, restore, running


def main() -> int:
    import objc
    from AppKit import (
        NSAlert, NSAlertFirstButtonReturn, NSApplication, NSApplicationActivationPolicyRegular,
        NSBackingStoreBuffered, NSButton, NSFont, NSModalResponseOK, NSObject, NSOpenPanel,
        NSProgressIndicator, NSProgressIndicatorStyleSpinning, NSTextField,
        NSTerminateCancel, NSTerminateNow, NSWindow, NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskTitled, NSWorkspace,
    )
    from Foundation import NSURL
    from PyObjCTools import AppHelper

    bundle = Path(sys.executable).absolute().parents[2]
    distribution = Distribution(bundle)
    SUPPORT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=SUPPORT / "patcher.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    class EndPlayDesktopPatcherDelegate(NSObject):
        def applicationDidFinishLaunching_(self, notification):
            self.target = DEFAULT_APP
            self.busy = False
            style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                ((0, 0), (620, 370)), style, NSBackingStoreBuffered, False)
            self.window.setTitle_("EndPlayDesktop 补丁工具")
            self.window.setReleasedWhenClosed_(False)
            self.window.setDelegate_(self)
            content = self.window.contentView()
            self.add_label(content, "EndPlayDesktop", (24, 306, 572, 36), 26, True)
            self.add_label(content, "为 MaaEnd 添加 EndPlayDesktop 控制器\n保留原有任务逻辑、版本号和官方更新。",
                           (24, 248, 572, 46), 14)
            self.path_label = self.add_label(content, str(self.target), (24, 196, 450, 28), 13)
            self.choose_button = self.add_button(content, "选择 MaaEnd…", (482, 194, 116, 32), "chooseApp:")
            self.apply_button = self.add_button(content, "应用补丁", (24, 126, 174, 40), "applyPatch:")
            self.apply_button.setKeyEquivalent_("\r")
            self.restore_button = self.add_button(content, "恢复备份", (218, 126, 174, 40), "restoreApp:")
            self.backups_button = self.add_button(content, "打开备份目录", (412, 126, 186, 40), "showBackups:")
            self.status_label = self.add_label(content, "选择 MaaEnd.app，然后点击“应用补丁”。", (24, 67, 572, 42), 13)
            self.spinner = NSProgressIndicator.alloc().initWithFrame_(((24, 27), (20, 20)))
            self.spinner.setStyle_(NSProgressIndicatorStyleSpinning)
            self.spinner.setDisplayedWhenStopped_(False)
            content.addSubview_(self.spinner)
            self.add_label(content, "内置运行环境 · 自动备份 · 无需安装开发工具", (52, 26, 546, 22), 12)
            self.window.center()
            self.window.makeKeyAndOrderFront_(None)
            application.activateIgnoringOtherApps_(True)

        @objc.python_method
        def add_label(self, content, text, frame, size, bold=False):
            label = NSTextField.wrappingLabelWithString_(text)
            label.setFrame_(((frame[0], frame[1]), (frame[2], frame[3])))
            label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
            content.addSubview_(label)
            return label

        @objc.python_method
        def add_button(self, content, title, frame, action):
            button = NSButton.buttonWithTitle_target_action_(title, self, action)
            button.setFrame_(((frame[0], frame[1]), (frame[2], frame[3])))
            content.addSubview_(button)
            return button

        def chooseApp_(self, sender):
            panel = NSOpenPanel.openPanel()
            panel.setTitle_("选择要添加控制器的 MaaEnd.app")
            panel.setAllowedFileTypes_(["app"])
            panel.setCanChooseDirectories_(False)
            panel.setAllowsMultipleSelection_(False)
            panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(self.target.parent)))
            if panel.runModal() == NSModalResponseOK:
                self.target = Path(panel.URL().path()).resolve()
                self.path_label.setStringValue_(str(self.target))
                try:
                    _, _, version = app_info(self.target)
                    self.status_label.setStringValue_(f"已选择 MaaEnd {version}。请先退出 MaaEnd，再应用补丁。")
                except Exception:
                    self.status_label.setStringValue_("请选择有效的 MaaEnd.app。")

        @objc.python_method
        def set_busy(self, busy, message):
            self.busy = busy
            for button in (self.choose_button, self.apply_button, self.restore_button, self.backups_button):
                button.setEnabled_(not busy)
            self.status_label.setStringValue_(message)
            if busy:
                self.spinner.startAnimation_(None)
            else:
                self.spinner.stopAnimation_(None)

        @objc.python_method
        def error(self, error):
            message = str(error)
            if "Quit MaaEnd" in message:
                message = "请先完全退出 MaaEnd，再重试。游戏无需退出。"
            elif isinstance(error, PermissionError):
                message = "无法写入所选位置。请将 MaaEnd 放到当前用户可写的目录后重试。"
            alert = NSAlert.alloc().init()
            alert.setMessageText_("未能完成操作")
            alert.setInformativeText_(message)
            alert.addButtonWithTitle_("知道了")
            alert.runModal()

        @objc.python_method
        def start_job(self, operation, message):
            self.set_busy(True, message)

            def worker():
                try:
                    result = operation()
                    AppHelper.callAfter(self.finish_job, result, None)
                except Exception as error:
                    logging.exception("Patcher operation failed")
                    AppHelper.callAfter(self.finish_job, None, error)

            threading.Thread(target=worker, name="EndPlayDesktopPatcher").start()

        @objc.python_method
        def finish_job(self, result, error):
            if error is not None:
                self.set_busy(False, "操作未完成，可重试；备份会保留。")
                self.error(error)
            elif result["status"] == "restored":
                self.set_busy(False, "已恢复备份，可以重新打开 MaaEnd。")
            else:
                self.set_busy(False, "补丁已就绪。打开 MaaEnd，选择 EndPlayDesktop 控制器即可使用。")

        def applyPatch_(self, sender):
            target = self.target.resolve()

            def operation():
                _, _, version = app_info(target)
                if running(target):
                    raise ValueError("Quit MaaEnd before applying the patch")
                runtime = distribution.install_runtime()
                payload = distribution.install_payload(version)
                return apply_patch(target, payload, runtime.project, SUPPORT / "backups", runtime.python)

            self.start_job(operation, "正在准备运行环境、备份并应用补丁，请稍候…")

        def restoreApp_(self, sender):
            target = self.target.resolve()
            try:
                backup = restore_backup(target)
                version = read_json(backup / "backup.json").get("maaend_version", "")
                alert = NSAlert.alloc().init()
                alert.setMessageText_("恢复备份？")
                alert.setInformativeText_(f"将恢复此 MaaEnd 的 {version} 备份。请先完全退出 MaaEnd。")
                alert.addButtonWithTitle_("恢复")
                alert.addButtonWithTitle_("取消")
                if alert.runModal() == NSAlertFirstButtonReturn:
                    self.start_job(lambda: restore(target, backup), "正在恢复 MaaEnd 备份，请稍候…")
            except Exception as error:
                self.error(error)

        def showBackups_(self, sender):
            directory = SUPPORT / "backups"
            directory.mkdir(parents=True, exist_ok=True)
            NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(directory)))

        def windowShouldClose_(self, sender):
            return not self.busy

        def applicationShouldTerminate_(self, sender):
            return NSTerminateCancel if self.busy else NSTerminateNow

        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            return True

    delegate = EndPlayDesktopPatcherDelegate.alloc().init()
    application.setDelegate_(delegate)
    AppHelper.runEventLoop()
    return 0
