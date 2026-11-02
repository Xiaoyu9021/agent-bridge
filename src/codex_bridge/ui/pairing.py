"""Copy/paste pairing dialogs; authorization stays local to the approving host."""
import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from codex_bridge.services.connection import invitation, parse_invitation


class PairingDialog(QDialog):
    requested = Signal(str, str)
    decided = Signal(str, bool)

    def __init__(self, runtime=None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.setWindowTitle("连接另一台电脑")
        self.resize(550, 370)
        layout = QVBoxLayout(self)
        title = QLabel("邀请另一台电脑加入" if runtime else "粘贴连接信息")
        title.setObjectName("brand")
        layout.addWidget(title)
        info = QLabel("两台电脑需在同一 Wi-Fi 或可信的私有网络中。普通局域网传输不加密。" if runtime else
                      "在创建连接的电脑上点击“连接另一台电脑”，复制连接信息后粘贴到这里。")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.copy_button = QPushButton("复制连接信息")
        self.copy_button.setObjectName("primary")
        self.copy_button.clicked.connect(self.copy)
        self.refresh_button = QPushButton("重新生成")
        self.refresh_button.clicked.connect(self.regenerate)
        self.code_text = QLabel("")
        self.code_text.setObjectName("muted")
        self.code_text.setWordWrap(True)
        self.waiting = QListWidget()
        self.waiting.setMaximumHeight(100)
        self.waiting.currentRowChanged.connect(self.selection_changed)
        self.allow_button = QPushButton("确认是我的电脑，允许连接")
        self.allow_button.setObjectName("primary")
        self.allow_button.clicked.connect(lambda: self.decide(True))
        self.reject_button = QPushButton("拒绝")
        self.reject_button.clicked.connect(lambda: self.decide(False))
        self.invite = QPlainTextEdit()
        self.invite.setMaximumHeight(90)
        self.invite.setPlaceholderText("在这里粘贴完整的连接信息")
        self.join_button = QPushButton("连接")
        self.join_button.setObjectName("primary")
        self.join_button.clicked.connect(self.join)
        self.manual_button = QPushButton("手动输入地址和连接码")
        self.manual_button.setCheckable(True)
        self.manual = QWidget()
        manual_layout = QVBoxLayout(self.manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        self.url = QLineEdit()
        self.url.setPlaceholderText("地址，如 http://192.168.1.20:47821")
        self.code = QLineEdit()
        self.code.setPlaceholderText("8 位连接码")
        manual_layout.addWidget(self.url)
        manual_layout.addWidget(self.code)
        self.manual_button.toggled.connect(self.manual.setVisible)
        if runtime:
            row = QHBoxLayout()
            row.addWidget(self.copy_button, 1)
            row.addWidget(self.refresh_button)
            layout.addLayout(row)
            layout.addWidget(self.code_text)
            cancel = QPushButton("取消本次邀请")
            cancel.clicked.connect(self.cancel_invitation)
            layout.addWidget(cancel)
            layout.addWidget(QLabel("收到连接申请后，核对设备名称再确认："))
            layout.addWidget(self.waiting)
            row = QHBoxLayout()
            row.addWidget(self.allow_button, 1)
            row.addWidget(self.reject_button)
            layout.addLayout(row)
        else:
            layout.addWidget(self.invite)
            layout.addWidget(self.join_button)
            layout.addWidget(self.manual_button)
            layout.addWidget(self.manual)
        self.manual.hide()
        # Non-applicable controls never appear as inactive product placeholders.
        for widget in ((self.invite, self.join_button, self.manual_button) if runtime else
                       (self.copy_button, self.refresh_button, self.code_text, self.waiting,
                        self.allow_button, self.reject_button)):
            widget.hide()
        layout.addWidget(self.status)
        layout.addStretch()
        done = QPushButton("返回任务页")
        done.clicked.connect(self.close)
        layout.addWidget(done)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.finished.connect(lambda _: self.timer.stop())

    def begin(self):
        if self.runtime:
            if not self.runtime.control.pending() and (
                    not self.runtime.control.code or self.runtime.control.expires < time.monotonic()):
                self.regenerate()
            self.refresh()
            self.timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    def regenerate(self):
        if self.runtime:
            self.runtime.control.open_pairing()
            self.status.setText("已生成连接信息。复制到另一台电脑，10 分钟内有效。")
            self.refresh()

    def cancel_invitation(self):
        self.runtime.control.close_pairing()
        self.status.setText("本次邀请已取消，尚未确认的连接申请已清除。")
        self.refresh()

    def copy(self):
        if not self.runtime.control.code or self.runtime.control.expires < time.monotonic():
            self.regenerate()
        if self.runtime.control.store.settings.host == "127.0.0.1":
            self.status.setText("目前没有可供另一台电脑使用的网络。请先连接 Wi-Fi，再在设置中启用自动选择网络并重启。")
            return
        text = invitation(self.runtime.url, self.runtime.control.code)
        QApplication.clipboard().setText(text)
        self.status.setText("已复制。到另一台电脑选择“加入连接”，粘贴后连接，再回来确认设备。")

    def refresh(self):
        if not self.runtime:
            return
        current = self.waiting.currentItem()
        selected = current.data(256) if current else None
        self.waiting.clear()
        for request in self.runtime.control.pending():
            item = QListWidgetItem(request["display_name"] + " · " + request["platform"])
            item.setData(256, request["request_id"])
            self.waiting.addItem(item)
            if selected == request["request_id"]:
                self.waiting.setCurrentItem(item)
        if self.waiting.count() == 1:
            self.waiting.setCurrentRow(0)
        control = self.runtime.control
        active = bool(control.code and control.expires > time.monotonic())
        self.code_text.setText(f"手动连接备用：{self.runtime.url}  ·  连接码 {control.code}" if active else
                               "连接信息已使用或过期。需要添加新电脑时点击“重新生成”。")
        self.selection_changed()

    def selection_changed(self, *_):
        selected = self.waiting.currentItem() is not None
        self.allow_button.setEnabled(selected)
        self.reject_button.setEnabled(selected)

    def decide(self, accepted):
        selected = self.waiting.currentItem()
        if selected:
            self.decided.emit(selected.data(256), accepted)

    def join(self):
        try:
            if self.invite.toPlainText().strip():
                url, code = parse_invitation(self.invite.toPlainText())
            else:
                from codex_bridge.client.api import normalize_url
                url, code = normalize_url(self.url.text()), self.code.text().strip()
                if len(code) != 8 or not code.isascii() or not code.isdigit():
                    raise ValueError("请粘贴连接信息，或填写正确的 8 位连接码")
            self.requested.emit(url, code)
        except ValueError as error:
            self.status.setText(str(error))
