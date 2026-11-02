"""Render real Qt UI with an isolated demo Host; no personal data or credentials in output."""
import os
import socket
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from codex_bridge.client.api import BridgeClient
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput, ResultInput, TaskInput
from codex_bridge.server.runtime import HostRuntime
from codex_bridge.services.files import describe_file
from codex_bridge.ui.app import STYLE, MainWindow, SetupDialog


def main():
    app = QApplication.instance() or QApplication([])
    # Windows offscreen plugin does not discover system fonts; reference installed fonts only.
    if os.name == "nt" and not QFontDatabase.families():
        for font in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf"):
            QFontDatabase.addApplicationFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    output = Path("docs/assets")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bridge-demo-") as temp:
        root = Path(temp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        settings = Settings(root / "host", port=port)
        host = DeviceInput(display_name="Windows · Android / 协调", platform="windows")
        mac = DeviceInput(display_name="MacBook · iOS / 执行", platform="macos")
        runtime = HostRuntime(settings, host)
        runtime.start()
        token = runtime.control.store.register(mac)
        sender = BridgeClient(runtime.url, host, runtime.control.token)
        receiver = BridgeClient(runtime.url, mac, token)
        try:
            source = root / "requirements.md"
            source.write_text(Path("examples/sample_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            model = TaskInput(title="iOS · 复刻 Android 个人中心", description_md=source.read_text(encoding="utf-8"),
                              recipient_device_id=mac.id, attachments=[describe_file(source)])
            sender.send_task(model, [source])
            for status in ["accepted", "in_progress"]:
                receiver.request("PATCH", f"/tasks/{model.id}/status", json={"status": status})
            report = root / "execution-report.md"
            report.write_text("# 示例执行报告\n\n已完成页面结构与接口约定核对。\n验证：演示数据流程通过；真实 iOS 工程尚未执行。", encoding="utf-8")
            result = ResultInput(summary_md="演示任务已完成交接，报告附件可下载。\n这是示例数据，不代表真实 iOS 项目开发结果。",
                                 outcome="completed", artifacts=[describe_file(report)])
            receiver.send_result(model.id, result, [report])
            second = TaskInput(title="iOS · 确认登录异常提示", description_md="请核对离线、超时及登录失效时的提示文案。",
                               recipient_device_id=mac.id)
            sender.send_task(second, [])
            prefs = {"mode": "host", "url": runtime.url, "host": "127.0.0.1", "port": port,
                     "download_dir": str(root / "downloads")}
            window = MainWindow(settings, host, prefs)
            window.client = sender
            window.runtime = runtime
            window.refresh = lambda: None
            window.apply_snapshot(sender.snapshot())
            window.connection.setText("● 已连接 · Windows · 本机双端演示（示例数据）")
            window.online = True
            window.new_task_button.setEnabled(True)
            window.tasks.setCurrentRow(1)
            window.progress_label.setText("结果附件已校验 · 可以下载或导出任务")
            window.progress.setValue(100)
            window.show()
            app.processEvents()
            window.grab().save(str(output / "desktop-demo.png"))
            setup = SetupDialog(settings, host, prefs)
            setup.show()
            app.processEvents()
            setup.grab().save(str(output / "setup-demo.png"))
            setup.close()
            joining = SetupDialog(settings, mac, {"mode": "client"})
            joining.show()
            app.processEvents()
            joining.grab().save(str(output / "setup-client-demo.png"))
            joining.close()
            window.ready_to_close = True
            window.close()
            print("Saved docs/assets/desktop-demo.png and setup-demo.png (isolated demo data)")
        finally:
            sender.close()
            receiver.close()
            runtime.close()


if __name__ == "__main__":
    main()
