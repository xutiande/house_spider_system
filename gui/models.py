# -*- coding: utf-8 -*-
"""表格模型。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Sequence, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return ("%f" % value).rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


class RecordModel(QAbstractTableModel):
    """固定列 + 追加行；最多保留 limit 行，避免长时间运行内存膨胀。"""

    def __init__(self, columns: Sequence[Tuple[str, str]], limit: int = 1000):
        super().__init__()
        self.columns = list(columns)
        self.rows: List[Dict[str, Any]] = []
        self.limit = limit

    # ---------------- Qt 接口 ----------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section][0]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key = self.columns[index.column()][1]
        if role == Qt.DisplayRole:
            if key == "_layout":
                return "%s室%s厅" % (row.get("room") or "-", row.get("hall") or "-")
            return _fmt(row.get(key))
        if role == Qt.TextAlignmentRole:
            value = row.get(key)
            if isinstance(value, (int, float, Decimal)):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and key in ("title", "loupan_name"):
            return _fmt(row.get(key))
        return None

    # ---------------- 数据操作 ----------------

    def set_columns(self, columns: Sequence[Tuple[str, str]]) -> None:
        self.beginResetModel()
        self.columns = list(columns)
        self.rows = []
        self.endResetModel()

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = list(rows)[: self.limit]
        self.endResetModel()

    def prepend(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        self.beginInsertRows(QModelIndex(), 0, len(rows) - 1)
        self.rows = (list(rows) + self.rows)[: self.limit]
        self.endInsertRows()
