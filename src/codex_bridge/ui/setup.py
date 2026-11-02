"""A short first-run flow; technical configuration is available on demand."""
from __future__ import annotations

import platform
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from codex_bridge.client.api import normalize_url
from codex_bridge.config import Settings
from codex_bridge.models import DeviceInput
from codex_bridge.services.connection import parse_invitation, suggested_host


class SetupDialog(QDialog):
    def __init__(self, settings: Settings, device: DeviceInput, prefs: dict, parent=None, configuring=False):
        super().__init__(parent)
        self.settings, self.prefs, self.configuring = settings, prefs, configuring
        self.initial_code = ""
        self.setWindowTitle("Codex Bridge · 开始使用" if not configuring else "Codex Bridge · 设置")
        self.resize(560, 390)
        layout = QVBoxLayout(self)
        title = QLabel("连接你的另一台电脑" if not configuring else "连接与保存设置")
        title.setObjectName("brand")
        layout.addWidget(title)
        intro = QLabel("两台电脑连接同一 Wi-Fi 或可信的私有网络，然后选择这台电脑要做什么。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        choices = QHBoxLayout()
        self.host_choice = QPushButton("创建连接\n让另一台电脑加入")
        self.client_choice = QPushButton("加入连接\n连接已准备好的电脑")
        self.roles = QButtonGroup(self)
        for index, widget in enumerate((self.host_choice, self.client_choice)):
            widget.setCheckable(True)
            widget.setMinimumHeight(70)
            choices.addWidget(widget)
            self.roles.addButton(widget, index)
        layout.addLayout(choices)
        self.roles.idClicked.connect(self.update_mode)
        self.host_note = QLabel("点击“开始使用”即可。网络、设备名称和保存位置会自动设置。")
        self.host_note.setWordWrap(True)
        layout.addWidget(self.host_note)
        self.invite_label = QLabel("粘贴另一台电脑复制的连接信息")
        layout.addWidget(self.invite_label)
        self.invite = QPlainTextEdit()
        self.invite.setMaximumHeight(72)
        self.invite.setPlaceholderText("在另一台电脑点击“连接另一台电脑”→“复制连接信息”，然后粘贴到这里。")
        layout.addWidget(self.invite)
        self.advanced_button = QPushButton("高级设置（通常不用改）")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_button)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.name = QLineEdit(device.display_name)
        self.auto_host = prefs.get("auto_host", prefs.get("host", settings.host) == "127.0.0.1")
        self.original_host = prefs.get("host", settings.host)
        self.host = QLineEdit("" if self.auto_host else self.original_host)
        self.host.setPlaceholderText("自动选择当前网络（留空即可）")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(prefs.get("port", settings.port))
        self.url = QLineEdit(prefs.get("url", ""))
        self.url.setPlaceholderText("仅供手动连接使用：http://私有IP:端口")
        self.manual_code = QLineEdit()
        self.manual_code.setPlaceholderText("另一台电脑的 8 位连接码")
        self.download = QLineEdit(prefs.get("download_dir", str(Path.home() / "Downloads" / "CodexBridge")))
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.download)
        pick = QPushButton("选择目录")
        pick.clicked.connect(self.choose_directory)
        directory_row.addWidget(pick)
        self.file_limit = QSpinBox()
        self.file_limit.setRange(1, 1024 * 1024)
        self.file_limit.setValue(prefs.get("max_file_bytes", settings.max_file_bytes) // 1024**2)
        self.task_limit = QSpinBox()
        self.task_limit.setRange(1, 1024 * 1024)
        self.task_limit.setValue(prefs.get("max_task_bytes", settings.max_task_bytes) // 1024**2)
        form.addRow("设备名称", self.name)
        form.addRow("监听 IP", self.host)
        form.addRow("端口", self.port)
        form.addRow("手动连接地址", self.url)
        form.addRow("手动连接码", self.manual_code)
        form.addRow("保存目录", directory_row)
        form.addRow("单文件上限（MiB）", self.file_limit)
        form.addRow("附件总量上限（MiB）", self.task_limit)
        advanced_layout.addLayout(form)
        note = QLabel(f"本地数据：{settings.data_dir}\n只连接你信任的电脑。普通 HTTP 不提供加密，请勿映射到公网。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        advanced_layout.addWidget(note)
        layout.addWidget(self.advanced)
        self.advanced.hide()
        self.actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.actions.accepted.connect(self.validate)
        self.actions.rejected.connect(self.reject)
        layout.addWidget(self.actions)
        mode = prefs.get("mode", "client" if platform.system() == "Darwin" else "host")
        (self.host_choice if mode == "host" else self.client_choice).setChecked(True)
        self.update_mode()

    def mode(self):
        return "host" if self.host_choice.isChecked() else "client"

    def update_mode(self, *_):
        host = self.mode() == "host"
        self.host_note.setVisible(host or self.configuring)
        self.host_note.setText("点击“开始使用”即可。网络、设备名称和保存位置会自动设置。" if host else
                               "已记住上次连接。需要重新配对时，在主界面点击“连接另一台电脑”。")
        self.invite_label.setVisible(not host and not self.configuring)
        self.invite.setVisible(not host and not self.configuring)
        for widget in (self.host, self.port, self.file_limit, self.task_limit):
            widget.setEnabled(host)
        self.url.setEnabled(not host)
        self.manual_code.setEnabled(not host)
        self.actions.button(QDialogButtonBox.StandardButton.Ok).setText(
            "保存" if self.configuring else "开始使用" if host else "连接")

    def toggle_advanced(self, checked):
        self.advanced.setVisible(checked)
        self.advanced_button.setText("收起高级设置" if checked else "高级设置（通常不用改）")
        if not checked:
            self.adjustSize()

    def choose_directory(self):
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", self.download.text())
        if folder:
            self.download.setText(folder)

    def values(self):
        host = self.host.text().strip()
        if self.mode() == "host" and not host:
            host = suggested_host()
        url = self.url.text().strip()
        code = self.manual_code.text().strip()
        if self.mode() == "client" and self.invite.toPlainText().strip():
            url, code = parse_invitation(self.invite.toPlainText())
        self.initial_code = code
        return {"mode": self.mode(), "display_name": self.name.text().strip(),
                "host": host or self.original_host, "auto_host": not self.host.text().strip(),
                "port": self.port.value(), "url": url, "download_dir": self.download.text().strip(),
                "max_file_bytes": self.file_limit.value() * 1024**2,
                "max_task_bytes": self.task_limit.value() * 1024**2}

    def validate(self):
        try:
            values = self.values()
            DeviceInput(display_name=values["display_name"], platform=platform.system().lower())
            if self.mode() == "host":
                Settings(Path("."), host=values["host"], port=values["port"],
                         max_file_bytes=values["max_file_bytes"], max_task_bytes=values["max_task_bytes"]).validate()
            else:
                if not self.configuring and not self.initial_code:
                    raise ValueError("请先粘贴另一台电脑复制的连接信息")
                normalize_url(values["url"])
                if self.initial_code and (len(self.initial_code) != 8 or not self.initial_code.isascii()
                                          or not self.initial_code.isdigit()):
                    raise ValueError("连接码应为 8 位数字，请重新复制连接信息")
            if not values["download_dir"]:
                raise ValueError("请选择保存目录")
            self.accept()
        except ValueError as error:
            QMessageBox.warning(self, "还需要一步", str(error))
