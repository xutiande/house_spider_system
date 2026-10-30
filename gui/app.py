# -*- coding: utf-8 -*-
"""主窗口与全局上下文。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from core.config import load_config
from gui.page_download import DownloadPage
from gui.page_main import MainPage
from gui.page_settings import SettingsPage
from gui.theme import STYLE, apply_palette, paint_gradient


class AppContext:
    """共享配置与懒加载的 API / Store。"""

    def __init__(self):
        self.cfg = load_config()
        self._api = None
        self._store = None

    def api(self):
        if self._api is None:
            from core.config import build_api
            self._api = build_api(self.cfg)
        return self._api

    def store(self):
        if self._store is None:
            from core.config import open_store
            self._store = open_store(self.cfg)
            try:
                # 启动时恢复上次异常退出遗留的 running 分片 / 任务
                self._store.recover_interrupted()
            except Exception:
                pass
        return self._store

    def reload(self) -> None:
        self.cfg = load_config()
        self._api = None
        self._store = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("安居客采集系统")
        self.resize(1320, 900)
        app = QApplication.instance()
        if app is not None:
            apply_palette(app)
        self.setStyleSheet(STYLE)
        self.ctx = AppContext()

        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet("#root { background: transparent; }")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 8)
        layout.setSpacing(12)

        header = QWidget()
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 0)
        title = QLabel("安居客采集系统")
        title.setObjectName("appTitle")
        subtitle = QLabel("城市 · 地点 · 房源采集")
        subtitle.setObjectName("appSubtitle")
        header_layout.addWidget(title)
        header_layout.addSpacing(12)
        header_layout.addWidget(subtitle)
        header_layout.addStretch(1)
        self.btn_exit = QPushButton("关闭程序")
        self.btn_exit.setObjectName("ghost")
        self.btn_exit.setToolTip("退出前会再次确认")
        self.btn_exit.clicked.connect(self.close)
        header_layout.addWidget(self.btn_exit)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.main_page = MainPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)
        self.download_page = DownloadPage(self.ctx)
        self.tabs.addTab(self.main_page, "主操作")
        self.tabs.addTab(self.settings_page, "设置")
        self.tabs.addTab(self.download_page, "数据下载")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(root)
        self.settings_page.saved.connect(self._on_settings_saved)
        self.statusBar().showMessage("就绪 · MySQL %s/%s"
                                     % (self.ctx.cfg["mysql"]["host"],
                                        self.ctx.cfg["mysql"]["database"]))

    def paintEvent(self, event) -> None:
        paint_gradient(self)

    def _on_settings_saved(self) -> None:
        self.statusBar().showMessage("配置已保存 · MySQL %s/%s"
                                     % (self.ctx.cfg["mysql"]["host"],
                                        self.ctx.cfg["mysql"]["database"]))

    def _confirm_close(self, running: bool) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("关闭确认 · 任务进行中" if running else "关闭确认")
        box.setIcon(QMessageBox.NoIcon)
        if running:
            box.setText("采集任务正在运行，确定退出吗？")
            box.setInformativeText(
                "退出会停止当前任务；已完成的分片和游标会保留，"
                "下次启动可点「继续上次」接着采。")
        else:
            box.setText("确定要关闭程序吗？")
        yes = box.addButton("确定退出", QMessageBox.YesRole)
        no = box.addButton("取消", QMessageBox.NoRole)
        box.setDefaultButton(no)
        box.setMinimumWidth(360)
        box.exec()
        return box.clickedButton() is yes

    def closeEvent(self, event) -> None:
        running = bool(self.main_page.runner and self.main_page.runner.isRunning())
        if not self._confirm_close(running):
            event.ignore()
            return

        self.main_page.shutdown()
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("安居客采集系统")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
