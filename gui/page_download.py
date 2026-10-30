# -*- coding: utf-8 -*-
"""数据下载页：按城市/地点统计并导出 CSV。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core.config import ROOT
from gui.common import current_city, fill_city_combo
from gui.workers import FuncWorker


class DownloadPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self._workers: List[FuncWorker] = []
        self._rows: List[Dict[str, Any]] = []
        self._loaded = False
        self._build()
        fill_city_combo(self.city_combo)
        self.city_combo.currentIndexChanged.connect(self._refresh)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded:
            self._loaded = True
            self._refresh()

    # ---------------- UI ----------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(QLabel("城市"))
        self.city_combo = QComboBox()
        self.city_combo.setMinimumWidth(220)
        top.addWidget(self.city_combo)

        self.radio_esf = QRadioButton("二手房")
        self.radio_xf = QRadioButton("新房")
        self.radio_esf.setChecked(True)
        self.radio_esf.toggled.connect(self._refresh)
        top.addWidget(self.radio_esf)
        top.addWidget(self.radio_xf)

        self.btn_refresh = QPushButton("刷新统计")
        self.btn_refresh.clicked.connect(self._refresh)
        top.addWidget(self.btn_refresh)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["地点", "数据量"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setFixedHeight(34)
        self.table.setColumnWidth(1, 120)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        table_box = QGroupBox("地点数据")
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(10, 14, 10, 10)
        table_layout.addWidget(self.table)
        layout.addWidget(table_box, 1)

        bottom = QHBoxLayout()
        self.btn_export_selected = QPushButton("导出选中地点")
        self.btn_export_selected.clicked.connect(self._export_selected)
        self.btn_export_all = QPushButton("导出全城")
        self.btn_export_all.clicked.connect(self._export_all)
        self.btn_open_dir = QPushButton("打开导出目录")
        self.btn_open_dir.clicked.connect(self._open_dir)
        bottom.addWidget(self.btn_export_selected)
        bottom.addWidget(self.btn_export_all)
        bottom.addWidget(self.btn_open_dir)
        bottom.addStretch(1)
        self.label = QLabel("")
        bottom.addWidget(self.label)
        layout.addLayout(bottom)

        self._update_buttons()

    # ---------------- 数据 ----------------

    def _refresh(self) -> None:
        city = current_city(self.city_combo)
        if not city:
            return
        biz = "xf" if self.radio_xf.isChecked() else "esf"
        self.label.setText("统计中…")
        worker = FuncWorker(self._load_counts, city["id"], biz)
        worker.done.connect(self._on_counts)
        worker.failed.connect(lambda msg: self.label.setText("失败：%s" % msg))
        self._workers.append(worker)
        worker.start()

    def _load_counts(self, city_id: int, biz: str) -> List[Dict[str, Any]]:
        store = self.ctx.store()
        return store.region_counts(city_id) if biz == "xf" else store.area_counts(city_id)

    def _on_counts(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(row["name"])))
            item = QTableWidgetItem(str(int(row["n"])))
            item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
            self.table.setItem(i, 1, item)
        total = sum(int(r["n"]) for r in rows)
        self.label.setText("共 %d 个地点，%d 条" % (len(rows), total))
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_rows = self.table.rowCount() > 0
        self.btn_export_all.setEnabled(has_rows)
        self.btn_export_selected.setEnabled(bool(self.table.selectedItems()))

    # ---------------- 导出 ----------------

    def _selected_name(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.text() if item else ""

    def _export_selected(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if name == "(未知)":
            name = ""
        self._export(name or None)

    def _export_all(self) -> None:
        self._export(None)

    def _export(self, name) -> None:
        """统计页点导出：选路径后交给后台线程流式写 CSV，避免卡界面。"""
        city = current_city(self.city_combo)
        if not city:
            return
        biz = "xf" if self.radio_xf.isChecked() else "esf"
        suffix = ("_" + name) if name else "_全城"
        default = str(ROOT / "exports" / ("%s%s_%s.csv" % (city["name"], suffix, biz)))
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", default,
                                              "CSV 文件 (*.csv)")
        if not path:
            return
        self.label.setText("导出中…")
        self.btn_export_all.setEnabled(False)
        self.btn_export_selected.setEnabled(False)

        if biz == "xf":
            fn = self.ctx.store().export_xf_csv
            args = (city["id"], path, name or "")
        else:
            fn = self.ctx.store().export_esf_csv
            args = (city["id"], path, name or "")

        worker = FuncWorker(fn, *args)
        worker.done.connect(lambda n: self._on_export(path, n))
        worker.failed.connect(self._on_export_fail)
        self._workers.append(worker)
        worker.start()

    def _on_export(self, path: str, count: int) -> None:
        self.label.setText("已导出 %d 条 -> %s" % (count, path))
        self._update_buttons()

    def _on_export_fail(self, message: str) -> None:
        self.label.setText("导出失败：%s" % message)
        self._update_buttons()
        QMessageBox.warning(self, "导出失败", message)

    def _open_dir(self) -> None:
        target = ROOT / "exports"
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
