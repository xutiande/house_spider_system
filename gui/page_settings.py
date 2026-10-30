# -*- coding: utf-8 -*-
"""设置页：MySQL 与代理。"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from core.api import ProxyPool
from core.config import save_config, test_mysql
from gui.workers import FuncWorker


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self._workers = []
        self._build()
        self._load()

    # ---------------- UI ----------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)

        mysql_box = QGroupBox("MySQL")
        form = QFormLayout(mysql_box)
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.database = QLineEdit()
        form.addRow("主机", self.host)
        form.addRow("端口", self.port)
        form.addRow("用户", self.user)
        form.addRow("密码", self.password)
        form.addRow("数据库", self.database)
        for field, width in ((self.host, 320), (self.port, 120), (self.user, 220),
                             (self.password, 260), (self.database, 260)):
            field.setMaximumWidth(width)

        row = QHBoxLayout()
        self.btn_test_db = QPushButton("测试连接")
        self.btn_test_db.clicked.connect(self._test_db)
        self.db_result = QLabel("未测试")
        self.db_result.setStyleSheet("color:#666")
        row.addWidget(self.btn_test_db)
        row.addWidget(self.db_result, 1)
        form.addRow("", row)
        layout.addWidget(mysql_box)

        proxy_box = QGroupBox("代理（可选）")
        pform = QFormLayout(proxy_box)
        self.proxy_enabled = QCheckBox("启用代理")
        pform.addRow("", self.proxy_enabled)

        source_row = QHBoxLayout()
        self.proxy_source = QLineEdit()
        self.proxy_source.setPlaceholderText("文件路径或返回 ip:port 行的 URL")
        self.proxy_source.setMaximumWidth(680)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.clicked.connect(self._browse)
        source_row.addWidget(self.proxy_source, 1)
        source_row.addWidget(self.btn_browse)
        source_row.addStretch(1)
        pform.addRow("来源", source_row)

        self.proxy_protocol = QComboBox()
        self.proxy_protocol.addItems(["http", "https", "socks5"])
        self.proxy_protocol.setMaximumWidth(180)
        pform.addRow("协议", self.proxy_protocol)

        self.proxy_user = QLineEdit()
        self.proxy_pass = QLineEdit()
        self.proxy_pass.setEchoMode(QLineEdit.Password)
        self.proxy_user.setMaximumWidth(260)
        self.proxy_pass.setMaximumWidth(260)
        pform.addRow("账号", self.proxy_user)
        pform.addRow("密码", self.proxy_pass)

        prow = QHBoxLayout()
        self.btn_test_proxy = QPushButton("加载并校验")
        self.btn_test_proxy.clicked.connect(self._test_proxy)
        self.proxy_result = QLabel("未测试")
        self.proxy_result.setStyleSheet("color:#666")
        prow.addWidget(self.btn_test_proxy)
        prow.addWidget(self.proxy_result, 1)
        pform.addRow("", prow)
        layout.addWidget(proxy_box)

        layout.addStretch(1)
        bottom = QHBoxLayout()
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("primary")
        self.btn_save.setMinimumHeight(38)
        self.btn_save.clicked.connect(self._save)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_save)
        layout.addLayout(bottom)

    # ---------------- 数据 ----------------

    def _load(self) -> None:
        cfg = self.ctx.cfg
        my = cfg.get("mysql", {})
        self.host.setText(str(my.get("host", "127.0.0.1")))
        self.port.setValue(int(my.get("port", 3306)))
        self.user.setText(str(my.get("user", "root")))
        self.password.setText(str(my.get("password", "")))
        self.database.setText(str(my.get("database", "ajk_crawl")))

        px = cfg.get("proxy", {})
        self.proxy_enabled.setChecked(bool(px.get("enabled")))
        self.proxy_source.setText(str(px.get("source", "")))
        index = self.proxy_protocol.findText(str(px.get("protocol", "http")))
        self.proxy_protocol.setCurrentIndex(max(0, index))
        self.proxy_user.setText(str(px.get("username", "")))
        self.proxy_pass.setText(str(px.get("password", "")))

    def _collect(self) -> Dict[str, Any]:
        cfg = self.ctx.cfg
        cfg.setdefault("mysql", {}).update({
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "user": self.user.text().strip(),
            "password": self.password.text(),
            "database": self.database.text().strip() or "ajk_crawl",
        })
        cfg.setdefault("proxy", {}).update({
            "enabled": self.proxy_enabled.isChecked(),
            "source": self.proxy_source.text().strip(),
            "protocol": self.proxy_protocol.currentText(),
            "username": self.proxy_user.text().strip(),
            "password": self.proxy_pass.text(),
        })
        return cfg

    # ---------------- 动作 ----------------

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择代理列表文件", "",
                                              "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self.proxy_source.setText(path)

    def _test_db(self) -> None:
        cfg = self._collect()
        self.db_result.setText("连接中…")
        self.btn_test_db.setEnabled(False)
        worker = FuncWorker(test_mysql, cfg)
        worker.done.connect(self._on_db_ok)
        worker.failed.connect(self._on_db_fail)
        self._workers.append(worker)
        worker.start()

    def _on_db_ok(self, message: str) -> None:
        self.btn_test_db.setEnabled(True)
        self.db_result.setText(str(message))

    def _on_db_fail(self, message: str) -> None:
        self.btn_test_db.setEnabled(True)
        self.db_result.setText("失败：%s" % message)

    def _test_proxy(self) -> None:
        cfg = self._collect()
        proxy = cfg.get("proxy", {})
        if not proxy.get("source"):
            QMessageBox.warning(self, "提示", "请先填写代理来源")
            return
        self.proxy_result.setText("校验中…")
        self.btn_test_proxy.setEnabled(False)
        worker = FuncWorker(
            ProxyPool.from_source,
            source=proxy["source"], protocol=proxy.get("protocol", "http"),
            username=proxy.get("username", ""), password=proxy.get("password", ""),
            check_url=proxy.get("check_url", "https://api.anjuke.com/"),
            concurrency=int(proxy.get("check_concurrency", 10)),
            timeout=float(proxy.get("check_timeout_s", 3)),
            verify=bool(cfg["crawler"].get("verify_ssl", True)),
        )
        worker.done.connect(self._on_proxy_ok)
        worker.failed.connect(self._on_proxy_fail)
        self._workers.append(worker)
        worker.start()

    def _on_proxy_ok(self, pool) -> None:
        self.btn_test_proxy.setEnabled(True)
        self.proxy_result.setText("可用 %d 个代理" % pool.available)

    def _on_proxy_fail(self, message: str) -> None:
        self.btn_test_proxy.setEnabled(True)
        self.proxy_result.setText("失败：%s" % message)

    def _save(self) -> None:
        cfg = self._collect()
        save_config(cfg)
        self.ctx.reload()
        self.saved.emit()
        QMessageBox.information(self, "已保存", "配置已写入 config/config.yaml")
