# -*- coding: utf-8 -*-
"""界面主题：浅绿 -> 白色渐变背景 + 简约控件样式。"""

from __future__ import annotations

import math

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

ASSETS = (Path(__file__).resolve().parent / "assets").as_posix()
ARROW_DOWN = "%s/chevron-down.svg" % ASSETS
ARROW_UP = "%s/chevron-up.svg" % ASSETS

# 主题色
GREEN_START = "#70f070"     # 顶部浅绿
GREEN_MID = "#c9f9d2"
WHITE = "#ffffff"
ACCENT = "#22b573"          # 主按钮
ACCENT_DARK = "#1a9c60"
TEXT = "#20342a"
MUTED = "#6b7f74"
CARD = "rgba(255, 255, 255, 0.94)"
BORDER = "#e3f0e8"

STYLE = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif; }
QWidget { color: %(TEXT)s; font-size: 10pt; }
QWidget#page { background: transparent; }
QMainWindow { background: transparent; }

/* ---------- 顶部标题 ---------- */
QLabel#appTitle { font-size: 19pt; font-weight: 700; color: #0d5c38; }
QLabel#appSubtitle { font-size: 9pt; color: #2f6b4c; }

/* ---------- 选项卡 ---------- */
QTabWidget::pane { border: none; background: transparent; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: rgba(255, 255, 255, 0.55);
    color: #24523a;
    padding: 9px 26px;
    margin-right: 8px;
    border: 1px solid rgba(255, 255, 255, 0.7);
    border-radius: 11px;
    font-size: 10pt;
}
QTabBar::tab:hover { background: rgba(255, 255, 255, 0.8); }
QTabBar::tab:selected {
    background: #ffffff;
    color: %(ACCENT_DARK)s;
    font-weight: 600;
    border: 1px solid #dff0e6;
}

/* ---------- 卡片 ---------- */
QGroupBox {
    background: %(CARD)s;
    border: 1px solid %(BORDER)s;
    border-radius: 14px;
    margin-top: 16px;
    padding: 20px 16px 14px 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 16px;
    top: 2px;
    padding: 0 6px;
    color: #2c5f43;
    font-weight: 600;
    background: transparent;
}

/* ---------- 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox {
    background: #f7fbf8;
    border: 1px solid #dcebe2;
    border-radius: 9px;
    padding: 6px 10px;
    min-height: 20px;
    selection-background-color: #bdeccd;
    selection-color: #123c28;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #7bdda2;
    background: #ffffff;
}

/* 下拉框：隐藏原生箭头，改用自带图标，避免与边框重叠 */
QComboBox { padding-right: 30px; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: url("%(ARROW_DOWN)s");
    width: 13px;
    height: 13px;
}
QComboBox::down-arrow:disabled { image: none; }

/* 数字框：上下箭头同样用图标 */
QSpinBox { padding-right: 22px; }
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    height: 15px;
    border: none;
    background: transparent;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    height: 15px;
    border: none;
    background: transparent;
}
QSpinBox::up-arrow {
    image: url("%(ARROW_UP)s");
    width: 10px;
    height: 10px;
}
QSpinBox::down-arrow {
    image: url("%(ARROW_DOWN)s");
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #dcebe2;
    border-radius: 8px;
    selection-background-color: #e6f9ee;
    selection-color: #12603c;
    outline: none;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: #ffffff;
    border: 1px solid #dcebe2;
    border-radius: 10px;
    padding: 7px 18px;
    color: #2c4a3a;
}
QPushButton:hover { background: #f3fcf6; border-color: #9fe3b8; }
QPushButton:pressed { background: #e8f8ef; }
QPushButton:disabled { color: #a9bcb1; background: #f4f7f5; border-color: #e8f0eb; }
QPushButton#primary {
    background: %(ACCENT)s;
    border: none;
    color: #ffffff;
    font-weight: 600;
    padding: 8px 24px;
}
QPushButton#primary:hover { background: %(ACCENT_DARK)s; }
QPushButton#primary:disabled { background: #b7e8ca; color: #f3fff8; }
QPushButton#ghost { background: transparent; border: 1px solid rgba(255,255,255,0.9); }

/* ---------- 树 / 表格 ---------- */
QTreeWidget, QTableView {
    background: #ffffff;
    border: 1px solid %(BORDER)s;
    border-radius: 10px;
    alternate-background-color: #fafdfb;
    selection-background-color: #e6f9ee;
    selection-color: #12603c;
    outline: none;
}
QTreeWidget::item { padding: 5px 2px; border-radius: 6px; }
QTreeWidget::item:hover { background: #f2fbf5; }
QTreeWidget:disabled { color: #a9bcb1; background: #f8fbf9; border-color: #eef4f0; }
QTreeView::branch { background: transparent; }
QHeaderView::section {
    background: #f2faf5;
    color: #46705a;
    border: none;
    border-bottom: 1px solid #e3f0e8;
    padding: 7px 8px;
    font-weight: 600;
}
QTableView QTableCornerButton::section { background: #f2faf5; border: none; }
QTableWidget { background: #ffffff; border: 1px solid %(BORDER)s; border-radius: 10px; }

/* ---------- 进度 / 日志 ---------- */
QProgressBar {
    background: #edf8f1;
    border: none;
    border-radius: 8px;
    height: 16px;
    text-align: center;
    color: #1c6b44;
    font-size: 9pt;
}
QProgressBar::chunk { background: #62d68e; border-radius: 8px; }
QPlainTextEdit {
    background: #fbfdfc;
    border: 1px solid %(BORDER)s;
    border-radius: 10px;
    padding: 6px;
    color: #33503f;
    font-family: "Consolas", "Microsoft YaHei UI", monospace;
    font-size: 9pt;
}

/* ---------- 其它 ---------- */
QLabel#hint { color: %(MUTED)s; font-size: 9pt; }
QLabel#sectionValue { color: #2c5f43; font-weight: 600; }
QStatusBar { background: transparent; color: #4d6a5c; }
QStatusBar::item { border: none; }
QSplitter::handle { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cfe8d9; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #a9d9bd; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cfe8d9; border-radius: 5px; min-width: 30px; }
QMessageBox { background: #ffffff; }
""" % {
    "TEXT": TEXT,
    "ACCENT": ACCENT,
    "ACCENT_DARK": ACCENT_DARK,
    "CARD": CARD,
    "BORDER": BORDER,
    "MUTED": MUTED,
    "ARROW_DOWN": ARROW_DOWN,
    "ARROW_UP": ARROW_UP,
}


def apply_palette(app) -> None:
    """把系统高亮色换成绿色，复选框/选中行才协调。"""
    from PySide6.QtGui import QPalette

    palette = app.palette()
    palette.setColor(QPalette.Highlight, QColor("#8ee6ae"))
    palette.setColor(QPalette.HighlightedText, QColor("#0d3b23"))
    app.setPalette(palette)


def paint_gradient(widget: QWidget) -> None:
    """从左上到右下、接近垂直的 80° 渐变：上 1/3 浅绿 -> 白。"""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    width = max(1, widget.width())
    height = max(1, widget.height())

    # 80°（相对水平线），即相对垂直方向偏 10°
    offset = height * math.tan(math.radians(10))
    gradient = QLinearGradient(QPointF(0, 0), QPointF(offset, height))
    gradient.setColorAt(0.00, QColor(GREEN_START))
    gradient.setColorAt(0.14, QColor("#a9f7bb"))
    gradient.setColorAt(0.26, QColor("#e0fbe7"))
    gradient.setColorAt(0.34, QColor(WHITE))
    gradient.setColorAt(1.00, QColor(WHITE))
    painter.fillRect(0, 0, width, height, gradient)
    painter.end()
