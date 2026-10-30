# -*- coding: utf-8 -*-
"""界面共用小工具。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from config.cityCode import CityList


def fill_city_combo(combo: QComboBox, default_id: int = 14) -> None:
    combo.blockSignals(True)
    combo.clear()
    for city in CityList:
        label = "%s · %s" % (city["name"], city["pinyin"])
        combo.addItem(label, city)
        if city["esf_available"] == 0:
            index = combo.count() - 1
            combo.model().item(index).setEnabled(False)
            combo.setItemData(index, "该城市探针无二手房数据", Qt.ToolTipRole)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    completer = QCompleter([combo.itemText(i) for i in range(combo.count())], combo)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setMaxVisibleItems(15)
    combo.setCompleter(completer)

    for i in range(combo.count()):
        data = combo.itemData(i)
        if data and data["id"] == default_id:
            combo.setCurrentIndex(i)
            break
    combo.blockSignals(False)


def current_city(combo: QComboBox) -> Optional[Dict[str, Any]]:
    index = combo.currentIndex()
    if index < 0:
        return None
    data = combo.itemData(index)
    return data if isinstance(data, dict) else None
