import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput
from codex_bridge.ui.app import MainWindow, SetupDialog


def wait_for(app, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        time.sleep(0.01)
        assert time.monotonic() < deadline, "Qt worker timed out"


def test_gui_worker_does_not_block_ui_and_callbacks_use_main_thread(tmp_path):
    app = QApplication.instance() or QApplication([])
    device = DeviceInput(display_name="测试设备", platform="windows")
    prefs = {"mode": "client", "url": "http://127.0.0.1:1", "download_dir": str(tmp_path)}
    window = MainWindow(Settings(tmp_path), device, prefs)
    # Prevent automatic connect for this isolated worker scheduling test.
    window.client = object()
    window.refresh = lambda: None
    callbacks = []
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    worker_threads = []
    def job(progress):
        worker_threads.append(threading.current_thread().name)
        time.sleep(0.3)
        progress("test", 1, 1)
        return 42
    window.operation("测试后台工作", job, lambda value: callbacks.append((value, QThread.currentThread())))
    wait_for(app, lambda: len(callbacks) == 1)
    timer.stop()
    assert callbacks[0] == (42, app.thread())
    assert len(ticks) >= 5
    assert worker_threads[0] != threading.current_thread().name
    assert window.progress.value() == 100
    window.ready_to_close = True
    window.close()


def test_setup_dialog_and_failure_retry(tmp_path):
    app = QApplication.instance() or QApplication([])
    device = DeviceInput(display_name="测试设备", platform="windows")
    settings = Settings(tmp_path)
    setup = SetupDialog(settings, device, {"mode": "host"})
    assert setup.values()["mode"] == "host"
    setup.client_choice.click()
    assert not setup.host.isEnabled() and setup.url.isEnabled()
    prefs = {"mode": "client", "url": "http://127.0.0.1:1", "download_dir": str(tmp_path)}
    window = MainWindow(settings, device, prefs)
    window.client = object()
    window.refresh = lambda: None
    attempts = []
    def job(progress):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("连接失败，请重试")
        return "ok"
    window.operation("传输", job)
    wait_for(app, lambda: not window.busy)
    assert window.progress.value() == 0
    assert window.retry_button.isEnabled()
    assert "失败" in window.progress_label.text()
    window.retry()
    wait_for(app, lambda: not window.busy)
    assert len(attempts) == 2 and window.progress.value() == 100
    window.ready_to_close = True
    window.close()
