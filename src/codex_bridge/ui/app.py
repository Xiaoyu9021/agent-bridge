from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from codex_bridge import __version__
from codex_bridge.client.api import BridgeClient
from codex_bridge.config import Settings
from codex_bridge.models import STATUS_NAMES, DeviceInput, ResultInput, TaskInput
from codex_bridge.server.runtime import HostRuntime
from codex_bridge.services.export import export_task
from codex_bridge.services.files import describe_file, format_size
from codex_bridge.services.identity import read_preferences, save_preferences, secure_token
from codex_bridge.storage.store import BridgeError
from codex_bridge.ui.pairing import PairingDialog
from codex_bridge.ui.setup import SetupDialog

STYLE = """
QMainWindow,QDialog { background: #f4f6fa; color: #17233b; }
QWidget { font-family: 'Microsoft YaHei UI','PingFang SC',sans-serif; font-size: 13px; }
QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox {
    background: white; border: 1px solid #d6deea; border-radius: 5px; padding: 7px;
    color: #17233b; selection-background-color: #dbeafe; selection-color: #153e75;
}
QPushButton { background: white; color: #17468f; border: 1px solid #c3d1e5;
    border-radius: 5px; padding: 8px 12px; }
QPushButton:hover { background: #e9f0fc; }
QPushButton:checked { background: #e2ecff; color: #17468f; border: 2px solid #245edb; }
QPushButton:disabled { color: #97a0af; background: #eef0f4; }
QPushButton#primary { background: #245edb; color: white; border: none; }
QLabel#brand { font-size: 24px; font-weight: 700; }
QLabel#muted { color: #61718a; }
QProgressBar { border: 1px solid #d6deea; border-radius: 4px; background: white;
    text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #73a0ed; }
"""


def button(text, callback, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(callback)
    return widget


def error_text(error: Exception) -> str:
    if isinstance(error, BridgeError):
        return error.message
    if isinstance(error, httpx.TimeoutException):
        return "连接或传输超时。检查主机地址与网络后点击重试；未完成文件不会标记为成功。"
    if isinstance(error, httpx.RequestError):
        return "无法连接任务中心。请检查 Host 是否启动、私有 IP、网络和防火墙，然后重试。"
    if isinstance(error, OSError):
        return "本地文件或网络操作失败，请检查文件是否存在、目录权限、磁盘空间及端口占用。"
    if isinstance(error, ValueError):
        return str(error)
    return "操作失败，请检查输入和连接配置。可重新尝试；问题持续时查看测试与故障排查文档。"


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(str, object, object)


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.last_progress = 0.0

    def progress(self, label, done, total):
        now = time.monotonic()
        if now - self.last_progress > 0.1 or done == total:
            self.last_progress = now
            self.signals.progress.emit(label, done, total)

    @Slot()
    def run(self):
        try:
            self.signals.succeeded.emit(self.function(self.progress))
        except Exception as error:
            self.signals.failed.emit(error)


class ComposeDialog(QDialog):
    def __init__(self, devices: list[dict], parent=None, result=False):
        super().__init__(parent)
        self.result = result
        self.paths = []
        self.setWindowTitle("提交执行结果" if result else "新建任务")
        self.resize(680, 580)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.target = QComboBox()
        for device in devices:
            self.target.addItem(device["display_name"], device["id"])
        self.title = QLineEdit()
        self.outcome = QComboBox()
        self.outcome.addItem("已完成", "completed")
        self.outcome.addItem("已失败 / 需进一步说明", "failed")
        if result:
            form.addRow("执行结果", self.outcome)
        else:
            form.addRow("发送给", QLabel(devices[0]["display_name"]) if len(devices) == 1 else self.target)
            form.addRow("任务标题", self.title)
        layout.addLayout(form)
        layout.addWidget(QLabel("完成了什么，还有什么问题" if result else "告诉另一台电脑要做什么"))
        self.body = QPlainTextEdit()
        layout.addWidget(self.body, 1)
        self.files = QListWidget()
        self.files.setMaximumHeight(110)
        layout.addWidget(self.files)
        file_actions = QHBoxLayout()
        file_actions.addWidget(button("添加附件", self.add_files))
        file_actions.addWidget(button("移除选中附件", self.remove_file))
        file_actions.addStretch()
        layout.addLayout(file_actions)
        note = QLabel("文件只会传输，不会自动运行或解压。不要添加 .env、私钥或账号凭据。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("提交" if result else "发送")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(self.validate)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择附件（任意类型）")
        suspicious = [path for path in files if Path(path).name.startswith(".env") or
                      Path(path).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".ps1", ".sh", ".bat", ".exe"}
                      or Path(path).name.startswith(("id_rsa", "id_ed25519"))]
        if suspicious:
            answer = QMessageBox.warning(self, "检查附件内容", "选择的文件可能包含凭据或可执行代码。\n"
                                         "请确认确实需要传送这些文件，且已移除秘密信息。",
                                         QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Ok:
                return
        for path in files:
            if path not in self.paths:
                self.paths.append(path)
                self.files.addItem(Path(path).name)

    def remove_file(self):
        index = self.files.currentRow()
        if index >= 0:
            self.paths.pop(index)
            self.files.takeItem(index)

    def validate(self):
        if not self.body.toPlainText().strip() or (not self.result and (
                not self.title.text().strip() or not self.target.currentData())):
            QMessageBox.warning(self, "信息不完整", "请填写正文、任务标题并选择目标设备。")
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, device: DeviceInput, prefs: dict, initial_pair_code=""):
        super().__init__()
        self.settings, self.device, self.prefs = settings, device, prefs
        self.client = None
        self.runtime = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.workers = set()
        self.busy = False
        self.polling = False
        self.online = False
        self.pair_request_id = None
        self.initial_pair_code = initial_pair_code
        self.pair_dialog = None
        self.next_status = None
        self.retry_action = None
        self.last_path = None
        self.closing = False
        self.ready_to_close = False
        self.snapshot = {"devices": [], "tasks": []}
        self.setWindowTitle("Codex Bridge · 开发任务交接")
        self.resize(1250, 840)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        heading = QHBoxLayout()
        brand = QLabel("Codex Bridge")
        brand.setObjectName("brand")
        heading.addWidget(brand)
        heading.addWidget(QLabel(f"V{__version__} · 开发任务与文件交接"))
        heading.addStretch()
        heading.addWidget(button("设置", self.configure))
        layout.addLayout(heading)
        self.connection = QLabel("正在启动…")
        layout.addWidget(self.connection)
        privacy = QLabel("只连接你信任的电脑 · 普通局域网传输不加密 · 无需共享 Codex 账号")
        privacy.setObjectName("muted")
        layout.addWidget(privacy)
        split = QSplitter()
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 8, 10, 0)
        side.addWidget(QLabel("我的电脑与已连接设备"))
        self.devices = QListWidget()
        self.devices.setMaximumHeight(180)
        side.addWidget(self.devices)
        side.addWidget(QLabel("任务视图"))
        self.filter = QComboBox()
        for label, key in [("全部任务", "all"), ("收到的任务", "received"), ("发出的任务", "sent"), ("已完成", "completed")]:
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self.render_tasks)
        side.addWidget(self.filter)
        self.connect_button = button("连接另一台电脑", self.pair, True)
        side.addWidget(self.connect_button)
        self.connection_help = QLabel("先连接另一台电脑，再发送你的第一个任务。")
        self.connection_help.setWordWrap(True)
        self.connection_help.setObjectName("muted")
        side.addWidget(self.connection_help)
        side.addStretch()
        split.addWidget(sidebar)
        center = QWidget()
        content = QVBoxLayout(center)
        content.setContentsMargins(8, 8, 0, 0)
        toolbar = QHBoxLayout()
        self.new_task_button = button("＋ 发送任务", self.compose, True)
        self.new_task_button.setEnabled(False)
        toolbar.addWidget(self.new_task_button)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题或任务 ID")
        self.search.textChanged.connect(self.render_tasks)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(button("刷新 / 重连", self.refresh))
        content.addLayout(toolbar)
        vertical = QSplitter(Qt.Orientation.Vertical)
        self.tasks = QListWidget()
        self.tasks.currentItemChanged.connect(self.render_detail)
        vertical.addWidget(self.tasks)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlaceholderText("选择任务查看指令、状态和执行反馈。\n任务导出后，请手动交给本机 Codex。")
        detail_layout.addWidget(self.body, 1)
        self.attachments = QListWidget()
        self.attachments.setMaximumHeight(100)
        detail_layout.addWidget(self.attachments)
        actions = QHBoxLayout()
        self.change_status_button = button("接收任务", self.change_status)
        self.submit_result_button = button("回传结果", self.submit_result)
        self.resume_button = button("继续发送草稿", self.resume_draft)
        for control in (self.change_status_button, self.submit_result_button, self.resume_button):
            actions.addWidget(control)
        actions.addStretch()
        detail_layout.addLayout(actions)
        file_actions = QHBoxLayout()
        file_actions.addWidget(button("下载选中附件", self.download))
        file_actions.addWidget(button("保存任务给 Codex", self.export))
        file_actions.addWidget(button("复制任务正文", self.copy_body))
        file_actions.addWidget(button("打开最近目录", self.open_directory))
        detail_layout.addLayout(file_actions)
        vertical.addWidget(detail)
        vertical.setSizes([230, 420])
        content.addWidget(vertical, 1)
        split.addWidget(center)
        split.setSizes([245, 945])
        layout.addWidget(split, 1)
        transfer = QHBoxLayout()
        self.progress_label = QLabel("就绪")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.retry_button = button("重试上次操作", self.retry)
        self.retry_button.setEnabled(False)
        transfer.addWidget(self.progress_label, 2)
        transfer.addWidget(self.progress, 2)
        transfer.addWidget(self.retry_button)
        layout.addLayout(transfer)
        self.setCentralWidget(root)
        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.refresh)
        QTimer.singleShot(0, self.connect)

    def launch_worker(self, function, success, failure, progress=False):
        worker = Worker(function)
        self.workers.add(worker)
        def done(value):
            self.workers.discard(worker)
            success(value)
        def failed(error):
            self.workers.discard(worker)
            failure(error)
        worker.signals.succeeded.connect(done)
        worker.signals.failed.connect(failed)
        if progress:
            worker.signals.progress.connect(self.update_progress)
        self.pool.start(worker)

    def update_progress(self, label, done, total):
        self.progress_label.setText(f"{label} · {format_size(done)} / {format_size(total)}")
        self.progress.setRange(0, 100)
        self.progress.setValue(int(done * 100 / total) if total else 100)

    def operation(self, label, function, success=None):
        if self.busy or self.closing:
            self.statusBar().showMessage("请等待当前操作完成", 4000)
            return
        self.busy = True
        self.retry_button.setEnabled(False)
        self.progress_label.setText(label)
        self.progress.setRange(0, 0)
        self.retry_action = lambda: self.operation(label, function, success)
        def completed(value):
            self.busy = False
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress_label.setText(label + " · 已完成")
            self.retry_action = None
            if success:
                success(value)
            self.refresh()
        def failed(error):
            self.busy = False
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress_label.setText("失败：" + error_text(error))
            self.progress_label.setToolTip(error_text(error))
            self.retry_button.setEnabled(True)
            self.statusBar().showMessage(error_text(error), 15000)
            if self.pair_dialog and self.pair_dialog.isVisible():
                self.pair_dialog.status.setText(error_text(error))
        self.launch_worker(function, completed, failed, True)

    def retry(self):
        if self.retry_action:
            self.retry_action()

    def connect(self):
        if self.client:
            return
        def establish(progress):
            if self.prefs["mode"] == "host":
                runtime = HostRuntime(self.settings, self.device)
                try:
                    runtime.start()
                    client = BridgeClient(runtime.url, self.device, runtime.control.token, self.settings.data_dir)
                except BaseException:
                    runtime.close()
                    raise
                return runtime, client, None
            url = self.prefs["url"]
            client = BridgeClient(url, self.device, cache_dir=self.settings.data_dir)
            client.token = secure_token(client.url, self.device.id) or ""
            return None, client, None
        def established(value):
            self.runtime, self.client, self.pair_request_id = value
            self.snapshot = self.client.cached_snapshot()
            self.apply_snapshot(self.snapshot)
            self.timer.start()
            if self.initial_pair_code:
                code, self.initial_pair_code = self.initial_pair_code, ""
                self.join_peer(self.client.url, code)
        self.operation("连接任务中心", establish, established)

    def refresh(self):
        if not self.client:
            if not self.busy:
                self.connect()
            return
        if self.polling or self.busy or self.closing:
            return
        self.polling = True
        client = self.client
        def poll(progress):
            pairing = None
            if self.pair_request_id:
                pairing = client.pair_poll(self.pair_request_id)
                if pairing["status"] == "approved":
                    pairing["saved"] = bool(secure_token(client.url, self.device.id, client.token))
            if not client.token:
                return {"pairing": pairing, "snapshot": None}
            return {"pairing": pairing, "snapshot": client.snapshot()}
        def refreshed(value):
            self.polling = False
            if client is not self.client:
                return
            pairing = value["pairing"]
            if pairing and pairing["status"] in {"approved", "rejected"}:
                self.pair_request_id = None
                if self.pair_dialog:
                    self.pair_dialog.status.setText("已连接，可以返回任务页发送任务。" if pairing["status"] == "approved"
                                                    else "另一台电脑拒绝了连接。请核对设备后重试。")
                self.statusBar().showMessage(
                    "配对成功，授权已保存到系统凭据库" if pairing.get("saved") else
                    "配对成功（授权仅保存在本次内存，下次可能需重新配对）" if pairing["status"] == "approved"
                    else "主机拒绝了配对请求", 15000)
            if value["snapshot"] is not None:
                self.online = True
                self.apply_snapshot(value["snapshot"])
                peers = [item for item in self.snapshot["devices"] if item["id"] != self.device.id]
                self.connection.setText("● 已连接 · 可以发送和接收任务" if peers else
                                        "● 已准备好 · 点击“连接另一台电脑”开始")
            else:
                self.connection.setText("○ 请在另一台电脑确认本机的连接申请" if self.pair_request_id else
                                        "○ 尚未连接 · 点击“连接另一台电脑”粘贴连接信息")
            if self.runtime:
                self.render_pairing()
        def failed(error):
            self.polling = False
            if client is not self.client:
                return
            self.online = False
            if isinstance(error, BridgeError) and error.status in {410, 403}:
                self.pair_request_id = None
            self.connection.setText("○ 连接已断开 · 正在自动重连，仍可查看本地历史")
            self.connection.setToolTip(error_text(error))
            self.new_task_button.setEnabled(False)
            if self.pair_dialog:
                self.pair_dialog.status.setText(error_text(error))
            if self.runtime:
                self.render_pairing()
        self.launch_worker(poll, refreshed, failed)

    def apply_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.devices.clear()
        now = datetime.now(timezone.utc)
        for device in snapshot["devices"]:
            last_seen = datetime.fromisoformat(device["last_seen"])
            connected = (now - last_seen).total_seconds() < 20
            item = QListWidgetItem(("● " if connected else "○ ") + device["display_name"])
            item.setData(Qt.ItemDataRole.UserRole, device["id"])
            item.setToolTip(f"{device['platform']} · {device['id']}")
            self.devices.addItem(item)
        self.render_tasks()
        has_peer = any(device["id"] != self.device.id for device in snapshot["devices"])
        self.connection_help.setVisible(not has_peer)
        self.new_task_button.setEnabled(has_peer and self.online)

    def selected_task(self):
        item = self.tasks.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            return next((task for task in self.snapshot["tasks"] if task["id"] == key), None)
        return None

    def render_tasks(self):
        selected = self.selected_task()
        key = selected["id"] if selected else None
        self.tasks.blockSignals(True)
        self.tasks.clear()
        query = self.search.text().casefold()
        view = self.filter.currentData()
        for task in self.snapshot["tasks"]:
            if query not in (task["title"] + task["id"]).casefold():
                continue
            if view == "received" and task["recipient_device_id"] != self.device.id:
                continue
            if view == "sent" and task["sender_device_id"] != self.device.id:
                continue
            if view == "completed" and task["status"] != "completed":
                continue
            when = datetime.fromisoformat(task["updated_at"]).astimezone().strftime("%m-%d %H:%M")
            direction = "收到" if task["recipient_device_id"] == self.device.id else "发出"
            item = QListWidgetItem(f"{task['title']}\n{direction} · {STATUS_NAMES[task['status']]} · {when}")
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            self.tasks.addItem(item)
            if task["id"] == key:
                self.tasks.setCurrentItem(item)
        self.tasks.blockSignals(False)
        self.render_detail()

    def render_detail(self, *_):
        task = self.selected_task()
        previous_file = self.attachments.currentItem()
        previous_id = previous_file.data(Qt.ItemDataRole.UserRole)["id"] if previous_file else None
        self.attachments.clear()
        recipient = bool(task and task["recipient_device_id"] == self.device.id and task["status"] != "draft")
        transition = {"pending": ("接收任务", "accepted"), "accepted": ("开始处理", "in_progress"),
                      "failed": ("重新开始", "in_progress")}.get(task["status"] if task else "")
        self.next_status = transition[1] if recipient and transition else None
        self.change_status_button.setText(transition[0] if transition else "处理中" if task and
                                          task["status"] == "in_progress" else "接收任务")
        self.change_status_button.setEnabled(self.next_status is not None)
        self.change_status_button.setVisible(self.next_status is not None)
        self.submit_result_button.setEnabled(recipient and task["status"] in {"in_progress", "completed", "failed"})
        self.submit_result_button.setVisible(self.submit_result_button.isEnabled())
        resumable = bool(task and (task["status"] == "draft" or
                                 any(not result["published"] for result in task["results"])))
        self.resume_button.setVisible(resumable)
        if not task:
            self.body.clear()
            return
        text = (f"{task['title']}\n{STATUS_NAMES[task['status']]}\n\n"
                f"{task['description_md']}\n")
        for result in task["results"]:
            text += (f"\n──── 执行反馈 · {STATUS_NAMES[result['outcome']]}"
                     f"{'（尚未发布）' if not result['published'] else ''} ────\n{result['summary_md']}\n")
        text += "\n──── 状态历史 ────\n"
        for event in task["events"]:
            text += (datetime.fromisoformat(event["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                     + " · " + STATUS_NAMES[event["status"]] + "\n")
        text += f"\n任务编号：{task['id']}\n"
        scroll = self.body.verticalScrollBar().value()
        self.body.setPlainText(text)
        self.body.verticalScrollBar().setValue(scroll)
        files = list(task["attachments"])
        for result in task["results"]:
            files.extend(result["artifacts"])
        for file in files:
            item = QListWidgetItem(f"{'输入' if file['kind'] == 'input' else '结果'} · "
                                   f"{file['original_filename']} · {format_size(file['size_bytes'])} · "
                                   f"{'已校验' if file['complete'] else '待上传'}")
            item.setData(Qt.ItemDataRole.UserRole, file)
            self.attachments.addItem(item)
            if file["id"] == previous_id:
                self.attachments.setCurrentItem(item)

    def pair(self):
        if not self.client:
            self.statusBar().showMessage("正在准备连接，请稍候。启动失败时可点击下方重试。", 5000)
            return
        if self.pair_dialog is None:
            self.pair_dialog = PairingDialog(self.runtime, self)
            self.pair_dialog.requested.connect(self.join_peer)
            self.pair_dialog.decided.connect(self.approve_request)
        self.pair_dialog.begin()

    def join_peer(self, url, code):
        if self.closing:
            return
        if self.busy:
            if self.pair_dialog:
                self.pair_dialog.status.setText("请等当前操作完成后再连接。")
            return
        if self.polling:
            if self.pair_dialog:
                self.pair_dialog.status.setText("正在结束上次连接，请稍候…")
            QTimer.singleShot(250, lambda: self.join_peer(url, code))
            return
        old_client = self.client
        def request(progress):
            client = BridgeClient(url, self.device, cache_dir=self.settings.data_dir)
            try:
                key = client.pair_request(code)
            except BaseException:
                client.close()
                raise
            if old_client:
                old_client.close()
            return client, key
        def requested(value):
            self.client, self.pair_request_id = value
            self.prefs["url"] = self.client.url
            save_preferences(self.settings.data_dir, self.prefs)
            self.connection.setText("○ 请在另一台电脑确认本机的连接申请")
            if self.pair_dialog:
                self.pair_dialog.invite.clear()
                self.pair_dialog.code.clear()
                self.pair_dialog.status.setText("申请已发出。请到另一台电脑确认，然后回到任务页。")
        self.operation("连接另一台电脑", request, requested)

    def render_pairing(self):
        pending = self.runtime.control.pending()
        self.connect_button.setText("有电脑请求连接 · 点击确认" if pending else "连接另一台电脑")
        if self.pair_dialog and self.pair_dialog.isVisible():
            self.pair_dialog.refresh()

    def approve_request(self, request_id, accepted):
        def completed(value):
            if self.pair_dialog:
                self.pair_dialog.status.setText("已允许连接，可以开始收发任务。" if accepted else "已拒绝本次连接。")
                self.pair_dialog.refresh()
        self.operation("确认连接" if accepted else "拒绝连接",
                       lambda progress: self.runtime.control.approve(request_id, accepted), completed)

    def manage_devices(self):
        if not self.runtime:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("管理已连接设备")
        dialog.resize(440, 300)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("解除连接后，该电脑需要重新配对。已下载的文件不会删除。"))
        devices = QListWidget()
        for device in self.snapshot["devices"]:
            if device["id"] != self.device.id:
                item = QListWidgetItem(device["display_name"])
                item.setData(Qt.ItemDataRole.UserRole, device["id"])
                devices.addItem(item)
        layout.addWidget(devices)
        def disconnect():
            item = devices.currentItem()
            if not item:
                return
            if QMessageBox.question(dialog, "解除连接", f"解除与 {item.text()} 的连接？") == QMessageBox.StandardButton.Yes:
                key = item.data(Qt.ItemDataRole.UserRole)
                dialog.accept()
                self.operation("解除设备连接", lambda progress: self.runtime.control.store.revoke(key))
        remove = button("解除选中设备的连接", disconnect)
        remove.setEnabled(False)
        devices.currentRowChanged.connect(lambda row: remove.setEnabled(row >= 0))
        layout.addWidget(remove)
        layout.addWidget(button("返回", dialog.close))
        dialog.exec()

    def require_task(self):
        task = self.selected_task()
        if not task:
            self.statusBar().showMessage("请先选择任务", 4000)
        return task

    def compose(self):
        if not self.client or self.busy:
            return
        devices = [device for device in self.snapshot["devices"] if device["id"] != self.device.id]
        dialog = ComposeDialog(devices, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        title, body, target = dialog.title.text().strip(), dialog.body.toPlainText(), dialog.target.currentData()
        paths = [Path(path) for path in dialog.paths]
        prepared = {}
        def send(progress):
            if "model" not in prepared:
                prepared["model"] = TaskInput(title=title, description_md=body, recipient_device_id=target,
                                              attachments=[describe_file(path, progress) for path in paths])
            return self.client.send_task(prepared["model"], paths, progress)
        self.operation("发送任务", send)

    def change_status(self):
        task = self.require_task()
        if task and self.next_status:
            key, status = task["id"], self.next_status
            self.operation("更新任务状态", lambda progress: self.client.request(
                "PATCH", f"/tasks/{key}/status", json={"status": status}))

    def submit_result(self):
        task = self.require_task()
        if not task or not self.client or self.busy:
            return
        if task["recipient_device_id"] != self.device.id:
            self.statusBar().showMessage("只有接收设备可以提交执行结果", 5000)
            return
        dialog = ComposeDialog([], self, result=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key, body, outcome = task["id"], dialog.body.toPlainText(), dialog.outcome.currentData()
        paths = [Path(path) for path in dialog.paths]
        prepared = {}
        def send(progress):
            if "model" not in prepared:
                prepared["model"] = ResultInput(summary_md=body, outcome=outcome,
                                                artifacts=[describe_file(path, progress) for path in paths])
            return self.client.send_result(key, prepared["model"], paths, progress)
        self.operation("提交执行结果", send)

    def resume_draft(self):
        task = self.require_task()
        if not task or not self.client or self.busy:
            return
        result = next((item for item in task["results"] if not item["published"]), None)
        if task["status"] != "draft" and result is None:
            self.statusBar().showMessage("当前任务没有待继续发送的草稿", 5000)
            return
        files = result["artifacts"] if result else task["attachments"]
        paths = []
        if files:
            chosen, _ = QFileDialog.getOpenFileNames(self, "重新选择草稿中全部原始附件（将按哈希匹配）")
            if not chosen:
                return
            paths = [Path(path) for path in chosen]
        key = task["id"]
        def resume(progress):
            described = [(path, describe_file(path, progress)) for path in paths]
            ordered = []
            for item in files:
                match = next((path for path, meta in described if meta.original_filename == item["original_filename"]
                              and meta.size_bytes == item["size_bytes"] and meta.sha256 == item["sha256"]), None)
                if not match:
                    raise ValueError("未找到草稿对应的原始附件，请重新选择全部文件；文件内容必须与发送时一致")
                ordered.append(match)
            declared = [{field: item[field] for field in ("id", "original_filename", "size_bytes", "sha256", "mime_type")}
                        for item in files]
            if result:
                model = ResultInput(id=result["id"], summary_md=result["summary_md"], outcome=result["outcome"],
                                    artifacts=declared)
                return self.client.send_result(key, model, ordered, progress)
            model = TaskInput(**{field: task[field] for field in (
                "id", "title", "project", "description_md", "recipient_device_id", "source_agent", "target_agent")},
                              attachments=declared)
            return self.client.send_task(model, ordered, progress)
        self.operation("继续发送草稿", resume)

    def choose_directory(self, title):
        folder = QFileDialog.getExistingDirectory(self, title, self.prefs["download_dir"])
        return Path(folder) if folder else None

    def record_path(self, path):
        self.last_path = path if path.is_dir() else path.parent
        self.statusBar().showMessage(f"已保存：{path}。可点击“打开最近目录”查看。", 20000)

    def download(self):
        item = self.attachments.currentItem()
        if not item or not self.client:
            return
        metadata = item.data(Qt.ItemDataRole.UserRole)
        directory = self.choose_directory("保存附件到目录")
        if directory:
            self.operation("下载并校验附件", lambda progress: self.client.download(metadata, directory, progress),
                           self.record_path)

    def export(self):
        task = self.require_task()
        if not task or not self.client:
            return
        directory = self.choose_directory("选择任务导出的父目录（自动创建新文件夹）")
        if directory:
            key = task["id"]
            self.operation("导出任务", lambda progress: export_task(self.client, key, directory, progress), self.record_path)

    def copy_body(self):
        task = self.require_task()
        if task:
            QApplication.clipboard().setText(task["description_md"])
            self.statusBar().showMessage("已复制任务正文。请在本机 Codex 中手动引用。", 5000)

    def open_directory(self):
        if self.last_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_path)))

    def configure(self):
        dialog = SetupDialog(self.settings, self.device, self.prefs, self, configuring=True)
        if self.runtime:
            dialog.layout().insertWidget(dialog.layout().count() - 1,
                                         button("管理已连接设备", self.manage_devices))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            values = dialog.values()
            self.device.display_name = values.pop("display_name")
            self.prefs.update(values, device=self.device.model_dump())
            save_preferences(self.settings.data_dir, self.prefs)
            QMessageBox.information(self, "设置已保存", "新设置将在下次启动时生效。请先完成当前传输，再关闭并重新启动。")

    def closeEvent(self, event):
        if self.ready_to_close:
            event.accept()
            return
        event.ignore()
        if self.busy or self.polling:
            self.statusBar().showMessage("正在完成网络操作，请等待完成后再关闭窗口。", 6000)
            return
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        if self.pair_dialog:
            self.pair_dialog.close()
        self.connection.setText("正在停止任务中心并关闭连接…")
        def shutdown(progress):
            if self.runtime:
                self.runtime.close()
            if self.client:
                self.client.close()
        def finished(value):
            self.ready_to_close = True
            self.close()
        def failed(error):
            self.closing = False
            self.timer.start()
            self.statusBar().showMessage(error_text(error), 10000)
        self.launch_worker(shutdown, finished, failed)


def apply_profile(settings: Settings, prefs: dict) -> bool:
    """Reuse non-secret settings on subsequent launches; reselect the current local network."""
    from codex_bridge.client.api import normalize_url
    from codex_bridge.services.connection import suggested_host
    if prefs.get("mode") not in {"host", "client"}:
        return False
    prefs.setdefault("download_dir", str(Path.home() / "Downloads" / "CodexBridge"))
    prefs.setdefault("port", settings.port)
    prefs.setdefault("max_file_bytes", settings.max_file_bytes)
    prefs.setdefault("max_task_bytes", settings.max_task_bytes)
    prefs.setdefault("host", settings.host)
    prefs.setdefault("auto_host", prefs["host"] == "127.0.0.1")
    try:
        if prefs["mode"] == "host":
            if prefs["auto_host"]:
                prefs["host"] = suggested_host()
        else:
            prefs["url"] = normalize_url(prefs.get("url", ""))
        settings.host, settings.port = prefs["host"], prefs["port"]
        settings.max_file_bytes, settings.max_task_bytes = prefs["max_file_bytes"], prefs["max_task_bytes"]
        settings.validate()
        return True
    except (ValueError, TypeError):
        return False


def run_gui(settings: Settings, device: DeviceInput) -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    prefs = read_preferences(settings.data_dir)
    initial_code = ""
    if not apply_profile(settings, prefs):
        setup = SetupDialog(settings, device, prefs)
        if setup.exec() != QDialog.DialogCode.Accepted:
            return 0
        values = setup.values()
        device.display_name = values.pop("display_name")
        prefs.update(values, device=device.model_dump())
        initial_code = setup.initial_code
        if not apply_profile(settings, prefs):
            return 1
    save_preferences(settings.data_dir, prefs)
    window = MainWindow(settings, device, prefs, initial_code)
    window.show()
    return app.exec()
