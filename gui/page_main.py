# -*- coding: utf-8 -*-
"""主操作页：任务配置 + 地点树 + 数据预览 + 日志。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton,
                               QSpinBox, QSplitter, QTabWidget, QTableView,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from core import parser
from core.api import ApiError
from core.engine import TaskBuilder
from gui.common import current_city, fill_city_combo
from gui.models import RecordModel
from gui.workers import FuncWorker, TaskRunner, dim_name

ESF_COLUMNS = [
    ("房源ID", "house_id"), ("小区", "community_name"), ("区域", "area_name"),
    ("总价(万)", "price_wan"), ("面积", "area"), ("户型", "_layout"),
    ("楼层", "floor_level"), ("标题", "title"),
]
XF_COLUMNS = [
    ("楼盘ID", "loupan_id"), ("楼盘名", "loupan_name"), ("区域", "region_title"),
    ("片区", "sub_region_title"), ("状态", "sale_title"),
    ("均价", "avg_price"), ("总价(万)", "total_price"),
    ("面积", "area_range"), ("地址", "address"),
]

ESF_WIDTHS = [115, 118, 60, 68, 58, 55, 95]
XF_WIDTHS = [88, 150, 68, 68, 54, 68, 64, 78]


class MainPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx
        self.runner: Optional[TaskRunner] = None
        self.workers: List[FuncWorker] = []
        self._city_cache: Dict[int, Any] = {}
        self._current_city_id: Optional[int] = None
        self._loading = False
        self._build()
        fill_city_combo(self.city_combo)
        self.city_combo.currentIndexChanged.connect(self._on_city_changed)
        self._on_city_changed()

    # ================= UI =================

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧：配置 + 地点 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        config_box = QGroupBox("任务配置")
        grid = QGridLayout(config_box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("城市"), 0, 0)
        self.city_combo = QComboBox()
        self.city_combo.setMinimumWidth(220)
        grid.addWidget(self.city_combo, 0, 1, 1, 3)

        grid.addWidget(QLabel("业务"), 1, 0)
        biz_row = QHBoxLayout()
        self.radio_esf = QRadioButton("二手房")
        self.radio_xf = QRadioButton("新房")
        self.radio_esf.setChecked(True)
        self.radio_esf.toggled.connect(self._on_biz_changed)
        self.radio_xf.toggled.connect(self._on_biz_changed)
        self.biz_group = QButtonGroup(self)
        self.biz_group.setExclusive(True)
        self.biz_group.addButton(self.radio_esf)
        self.biz_group.addButton(self.radio_xf)
        biz_row.addWidget(self.radio_esf)
        biz_row.addWidget(self.radio_xf)
        biz_row.addStretch(1)
        grid.addLayout(biz_row, 1, 1, 1, 3)

        grid.addWidget(QLabel("关键词"), 2, 0)
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("输入关键词搜索；留空则按下方地点采集")
        self.keyword.textChanged.connect(self._on_keyword_changed)
        grid.addWidget(self.keyword, 2, 1, 1, 3)

        grid.addWidget(QLabel("页数"), 3, 0)
        page_row = QHBoxLayout()
        self.page_all = QRadioButton("全量")
        self.page_limit = QRadioButton("指定页数")
        self.page_all.setChecked(True)
        self.page_all.toggled.connect(self._on_page_mode)
        self.page_limit.toggled.connect(self._on_page_mode)
        self.page_group = QButtonGroup(self)
        self.page_group.setExclusive(True)
        self.page_group.addButton(self.page_all)
        self.page_group.addButton(self.page_limit)
        self.pages = QSpinBox()
        self.pages.setRange(1, 60)
        self.pages.setValue(5)
        self.pages.setEnabled(False)
        page_row.addWidget(self.page_all)
        page_row.addWidget(self.page_limit)
        page_row.addWidget(self.pages)
        page_row.addStretch(1)
        grid.addLayout(page_row, 3, 1)

        grid.addWidget(QLabel("并发"), 3, 2)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 12)
        self.concurrency.setValue(4)
        grid.addWidget(self.concurrency, 3, 3)

        grid.addWidget(QLabel("间隔(ms)"), 4, 0)
        self.interval = QSpinBox()
        self.interval.setRange(200, 5000)
        self.interval.setSingleStep(100)
        self.interval.setValue(int(self.ctx.cfg["crawler"].get("interval_ms", 800)))
        grid.addWidget(self.interval, 4, 1)

        self.proxy_check = QCheckBox("使用代理")
        self.proxy_check.setChecked(bool(self.ctx.cfg["proxy"].get("enabled")))
        grid.addWidget(self.proxy_check, 4, 2, 1, 2)

        left_layout.addWidget(config_box)

        self.location_box = QGroupBox("采集地点（不勾选 = 全城）")
        loc_layout = QVBoxLayout(self.location_box)
        loc_layout.setContentsMargins(12, 16, 12, 12)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("locationTabs")
        self.area_tree = QTreeWidget()
        self.area_tree.setHeaderLabels(["区 / 商圈", "ID"])
        self.area_tree.setColumnWidth(0, 200)
        self.area_tree.setMinimumHeight(170)
        self.area_tree.itemChanged.connect(self._on_area_item_changed)
        self.metro_tree = QTreeWidget()
        self.metro_tree.setHeaderLabels(["地铁线 / 站", "ID"])
        self.metro_tree.setColumnWidth(0, 200)
        self.metro_tree.setMinimumHeight(170)
        self.metro_tree.itemChanged.connect(self._on_metro_item_changed)
        self.tabs.addTab(self.area_tree, "区 / 商圈")
        self.tabs.addTab(self.metro_tree, "地铁")
        loc_layout.addWidget(self.tabs)
        left_layout.addWidget(self.location_box, 1)

        # ---- 右侧：预览 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        preview_box = QGroupBox("数据预览")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 16, 12, 12)
        toolbar = QHBoxLayout()
        self.preview_info = QLabel("尚未采集")
        self.preview_info.setObjectName("hint")
        toolbar.addWidget(self.preview_info, 1)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_preview)
        toolbar.addWidget(self.btn_refresh)
        preview_layout.addLayout(toolbar)

        self.model = RecordModel(ESF_COLUMNS, limit=500)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setCornerButtonEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.horizontalHeader().setFixedHeight(34)
        self.table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.table, 1)
        self._apply_column_widths()

        right_layout.addWidget(preview_box, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([410, 800])
        root.addWidget(splitter, 1)

        # ---- 底部：操作 + 日志 ----
        bottom = QGroupBox("运行状态")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(12, 16, 12, 12)
        bottom_layout.setSpacing(8)

        actions = QHBoxLayout()
        self.btn_start = QPushButton("开始采集")
        self.btn_start.setObjectName("primary")
        self.btn_start.setMinimumHeight(38)
        self.btn_start.clicked.connect(self._start)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(lambda: self._stop_runner(True))
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(lambda: self._stop_runner(False))
        self.btn_resume = QPushButton("继续上次")
        self.btn_resume.setToolTip("继续该城市最近一次暂停/停止的任务")
        self.btn_resume.clicked.connect(self._resume)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_resume.setEnabled(False)
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_resume)
        actions.addWidget(self.btn_pause)
        actions.addWidget(self.btn_stop)
        actions.addSpacing(16)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("%v / %m 分片")
        actions.addWidget(self.progress, 1)
        bottom_layout.addLayout(actions)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("hint")
        bottom_layout.addWidget(self.status_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFixedHeight(82)
        bottom_layout.addWidget(self.log_view)

        root.addWidget(bottom)

    # ================= 城市 / 地点 =================

    def _on_city_changed(self) -> None:
        city = current_city(self.city_combo)
        if not city or self._loading:
            return
        self._current_city_id = city["id"]
        if city["id"] in self._city_cache:
            self._populate(*self._city_cache[city["id"]])
            return
        self._set_location_enabled(False)
        self.status_label.setText("加载 %s 的地点…" % city["name"])
        worker = FuncWorker(self._fetch_city, city)
        worker.done.connect(self._on_city_loaded)
        worker.failed.connect(self._on_city_failed)
        self.workers.append(worker)
        worker.start()

    def _fetch_city(self, city: Dict[str, Any]):
        """接口1（区/地铁）与区域树各自容错：任一边失败都不影响另一边。"""
        api = self.ctx.api()
        store = self.ctx.store()
        warnings: List[str] = []

        meta = {"areas": [], "lines": [], "stations": []}
        try:
            meta = parser.parse_city_meta(api.city_meta(city["id"], city["abbr"]))
        except ApiError as exc:
            warnings.append("地铁/地点接口不可用（%s）" % exc)

        filters: List[Dict[str, Any]] = []
        try:
            filters = parser.parse_area_filters(api.area_filters(city["id"]))
        except ApiError as exc:
            warnings.append("区域树接口不可用（%s）" % exc)

        if filters:
            store.save_area_filters(city["id"], filters)
        if meta["areas"] or meta["lines"] or meta["stations"]:
            store.save_city_meta(city["id"], meta)
        return meta, filters, warnings

    def _on_city_loaded(self, result) -> None:
        meta, filters, warnings = result
        self._city_cache[self._current_city_id] = (meta, filters)
        self._populate(meta, filters)
        city = current_city(self.city_combo)
        name = city["name"] if city else ""
        for message in warnings:
            self._append_log("WARN", "%s：%s" % (name, message))

        if not filters and not meta["lines"]:
            self.status_label.setText("%s 暂无地点/地铁数据，可按全城采集" % name)
        elif not meta["lines"]:
            self.status_label.setText("已加载 %d 个区 / %d 个商圈（该城市无地铁数据）"
                                      % (len(filters),
                                         sum(len(f["shangquan"]) for f in filters)))
        else:
            self.status_label.setText("已加载 %d 个区、%d 条地铁线"
                                      % (len(filters), len(meta["lines"])))
        self._append_log("INFO", "%s：区 %d / 商圈 %d / 地铁站 %d" % (
            name, len(filters), sum(len(f["shangquan"]) for f in filters),
            len(meta["stations"])))
        self._refresh_resume()

    def _on_city_failed(self, message: str) -> None:
        self.btn_start.setEnabled(True)
        self._update_location_state()
        self.status_label.setText("地点加载失败")
        self._append_log("ERROR", "地点加载失败：%s" % message)

    def _populate(self, meta, filters) -> None:
        self.area_tree.blockSignals(True)
        self.area_tree.clear()
        for item in filters:
            top = QTreeWidgetItem([item["name"], str(item["area_id"])])
            top.setData(0, Qt.UserRole, ("area", item["area_id"], item["name"]))
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            top.setCheckState(0, Qt.Unchecked)
            for sq in item["shangquan"]:
                child = QTreeWidgetItem([sq["name"], str(sq["shangquan_id"])])
                child.setData(0, Qt.UserRole,
                              ("shangquan", sq["shangquan_id"], sq["name"]))
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                top.addChild(child)
            self.area_tree.addTopLevelItem(top)
        if not filters:
            placeholder = QTreeWidgetItem(["（该城市暂无区/商圈数据）", ""])
            placeholder.setFlags(Qt.NoItemFlags)
            self.area_tree.addTopLevelItem(placeholder)
        self.area_tree.blockSignals(False)

        self.metro_tree.blockSignals(True)
        self.metro_tree.clear()
        line_items: Dict[int, QTreeWidgetItem] = {}
        for line in meta["lines"]:
            node = QTreeWidgetItem([line["name"], str(line["line_id"])])
            node.setData(0, Qt.UserRole, ("line", line["line_id"], line["name"]))
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable)
            node.setCheckState(0, Qt.Unchecked)
            self.metro_tree.addTopLevelItem(node)
            line_items[line["line_id"]] = node
        for station in meta["stations"]:
            parent = line_items.get(station["line_id"])
            if not parent:
                continue
            child = QTreeWidgetItem([station["name"], str(station["station_id"])])
            child.setData(0, Qt.UserRole,
                          ("station", station["station_id"], station["name"]))
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Unchecked)
            parent.addChild(child)
        if not meta["lines"]:
            placeholder = QTreeWidgetItem(["（该城市暂无地铁数据）", ""])
            placeholder.setFlags(Qt.NoItemFlags)
            self.metro_tree.addTopLevelItem(placeholder)
        self.metro_tree.blockSignals(False)

        self.btn_start.setEnabled(True)
        self._update_location_state()

    def _set_location_enabled(self, enabled: bool) -> None:
        self.tabs.setEnabled(enabled)
        self.btn_start.setEnabled(
            enabled and not (self.runner and self.runner.isRunning()))

    def _on_area_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None and item.checkState(0) == Qt.Checked:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.checkState(0) == Qt.Checked:
                    child.setCheckState(0, Qt.Unchecked)
        elif item.parent() is not None and item.checkState(0) == Qt.Checked:
            parent = item.parent()
            if parent.checkState(0) == Qt.Checked:
                parent.setCheckState(0, Qt.Unchecked)

    def _on_metro_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if item.parent() is None and item.checkState(0) == Qt.Checked:
            for i in range(item.childCount()):
                child = item.child(i)
                if child.checkState(0) == Qt.Checked:
                    child.setCheckState(0, Qt.Unchecked)
        elif item.parent() is not None and item.checkState(0) == Qt.Checked:
            parent = item.parent()
            if parent.checkState(0) == Qt.Checked:
                parent.setCheckState(0, Qt.Unchecked)

    def _on_biz_changed(self, checked: bool = False) -> None:
        """二手房/新房 二选一；程序化 setChecked 时也保证互斥。"""
        if checked:
            other = self.radio_xf if self.sender() is self.radio_esf else self.radio_esf
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
        self._set_esf_preview(not self.radio_xf.isChecked())
        self._update_location_state()

    def _on_keyword_changed(self, text: str) -> None:
        self._update_location_state()

    def _on_page_mode(self, checked: bool = False) -> None:
        """全量 / 指定页数 二选一；程序化 setChecked 时也保证互斥。"""
        if checked:
            other = self.page_all if self.sender() is self.page_limit else self.page_limit
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
        self.pages.setEnabled(self.page_limit.isChecked())

    def _update_location_state(self) -> None:
        """关键词搜索 / 新房 时不需要（也不允许）选择地点。"""
        is_xf = self.radio_xf.isChecked()
        has_keyword = bool(self.keyword.text().strip())
        enabled = not is_xf and not has_keyword
        self.tabs.setEnabled(enabled)
        if is_xf:
            self.location_box.setTitle("采集地点（新房仅支持全城）")
        elif has_keyword:
            self.location_box.setTitle("采集地点（关键词搜索时忽略）")
        else:
            self.location_box.setTitle("采集地点（不勾选 = 全城）")

    # ================= 任务 =================

    def _selections(self) -> List[Dict[str, Any]]:
        """把两棵树里勾选的节点转成 [{dim, dim_id, name}]；空 = 全城。"""
        if self.radio_xf.isChecked():
            return [{"dim": "city", "dim_id": 0, "name": "全城"}]
        result: List[Dict[str, Any]] = []
        for i in range(self.area_tree.topLevelItemCount()):
            top = self.area_tree.topLevelItem(i)
            if top.checkState(0) == Qt.Checked:
                data = top.data(0, Qt.UserRole)
                result.append({"dim": "area", "dim_id": data[1], "name": data[2]})
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.Checked:
                    data = child.data(0, Qt.UserRole)
                    result.append({"dim": "shangquan", "dim_id": data[1],
                                   "name": data[2]})
        for i in range(self.metro_tree.topLevelItemCount()):
            top = self.metro_tree.topLevelItem(i)
            if top.checkState(0) == Qt.Checked:
                data = top.data(0, Qt.UserRole)
                result.append({"dim": "line", "dim_id": data[1], "name": data[2]})
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.Checked:
                    data = child.data(0, Qt.UserRole)
                    result.append({"dim": "station", "dim_id": data[1],
                                   "name": data[2]})
        if not result:
            result = [{"dim": "city", "dim_id": 0, "name": "全城"}]
        return result

    def _start(self) -> None:
        if self.runner and self.runner.isRunning():
            return
        city = current_city(self.city_combo)
        if not city:
            QMessageBox.warning(self, "提示", "请选择城市")
            return

        biz = "xf" if self.radio_xf.isChecked() else "esf"
        keyword = self.keyword.text().strip()
        mode = "search" if keyword else "browse"
        pages = 0 if self.page_all.isChecked() else self.pages.value()
        # 关键词搜索不按地点筛选，统一走全城
        selections = ([{"dim": "city", "dim_id": 0, "name": "全城"}]
                      if keyword else self._selections())

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.progress.setRange(0, 0)
        self.status_label.setText("正在展开分片（探针请求中）…")
        self._append_log("INFO", "开始：%s / %s / %s / %d 个选择"
                         % (city["name"], biz, mode, len(selections)))

        worker = FuncWorker(self._create_task, city, biz, mode, keyword,
                            pages, selections, self.concurrency.value(),
                            self.interval.value(),
                            int(self.proxy_check.isChecked()))
        worker.done.connect(self._on_task_created)
        worker.failed.connect(self._on_task_failed)
        self.workers.append(worker)
        worker.start()

    def _create_task(self, city, biz, mode, keyword, pages, selections,
                     concurrency, interval_ms, use_proxy):
        """后台线程：建任务 -> 探针展开分片 -> 写 task_shard。"""
        store = self.ctx.store()
        api = self.ctx.api()
        page_limit = pages if pages > 0 else 60
        name = "%s-%s-%s" % (city["name"], biz, time.strftime("%m%d-%H%M%S"))
        task_id = store.create_task(
            name, biz, mode, city["id"], keyword, page_limit,
            concurrency, interval_ms, use_proxy)
        messages: List[str] = []
        # expand 里会发探针请求（可能十几秒），所以放在后台线程
        builder = TaskBuilder(api, store, log=messages.append)
        shards = builder.expand(city["id"], biz, mode, keyword, selections,
                                page_limit=page_limit)
        if not shards:
            raise RuntimeError("没有可采集的分片（探针返回 0 条）")
        store.add_shards(task_id, shards)
        return task_id, shards, messages

    def _on_task_created(self, result) -> None:
        task_id, shards, messages = result
        for msg in messages:
            self._append_log("INFO", msg)

        task = self.ctx.store().get_task(task_id)
        if not task:
            self._on_task_failed("任务创建后读取失败")
            return

        self.progress.setRange(0, max(1, len(shards)))
        self.progress.setValue(0)
        self._launch(task)
        self._append_log("INFO", "任务 #%d 已创建，%d 个分片" % (task_id, len(shards)))

    def _launch(self, task: Dict[str, Any]) -> None:
        """启动（或继续）一个已存在的任务。"""
        self.runner = TaskRunner(
            self.ctx.api(), self.ctx.store(), task,
            interval_ms=self.interval.value(),
            jitter_ms=int(self.ctx.cfg["crawler"].get("jitter_ms", 700)))
        self.runner.progress.connect(self._on_progress)
        self.runner.records.connect(self._on_records)
        self.runner.log.connect(self._append_log)
        self.runner.finished_task.connect(self._on_finished)
        self.runner.finished.connect(self._refresh_resume)
        self.runner.start()

        self.btn_start.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.progress.setRange(0, max(1, int(task.get("total_shards") or 1)))
        self.progress.setValue(int(task.get("done_shards") or 0))
        self.status_label.setText("任务 #%s 运行中" % task["id"])
        self._set_preview_columns()

    def _resume(self) -> None:
        """继续该城市最近一次 paused/stopped/pending 任务（按分片游标）。"""
        city = current_city(self.city_combo)
        if not city:
            return
        task = self.ctx.store().unfinished_task(city["id"])
        if not task:
            QMessageBox.information(self, "没有可继续的任务", "该城市没有暂停/停止的任务")
            self.btn_resume.setEnabled(False)
            return
        self.ctx.store().set_task_status(int(task["id"]), "running")
        self._append_log("INFO", "继续任务 #%s（已完成 %s/%s 分片）"
                         % (task["id"], task.get("done_shards"),
                            task.get("total_shards")))
        self._launch(task)

    def _refresh_resume(self) -> None:
        city = current_city(self.city_combo)
        if not city:
            self.btn_resume.setEnabled(False)
            return
        try:
            task = self.ctx.store().unfinished_task(city["id"])
        except Exception:  # noqa: BLE001
            task = None
        # 只认数据库状态：running 的任务不会被 unfinished_task 返回
        self.btn_resume.setEnabled(bool(task))
        if task:
            self.btn_resume.setToolTip("继续任务 #%s（%s/%s 分片）"
                                       % (task["id"], task.get("done_shards"),
                                          task.get("total_shards")))

    def _on_task_failed(self, message: str) -> None:
        self.btn_start.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status_label.setText("任务创建失败")
        self._append_log("ERROR", "任务创建失败：%s" % message)
        QMessageBox.warning(self, "任务创建失败", message)

    def _stop_runner(self, paused: bool) -> None:
        if not self.runner:
            return
        self.runner.request_stop(paused=paused)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("正在%s…" % ("暂停" if paused else "停止"))

    def _on_progress(self, data: Dict[str, Any]) -> None:
        total = int(data.get("total") or 0)
        done = int(data.get("done") or 0)
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        fetched = data.get("fetched") or 0
        parts = ["分片 %d/%d" % (done, total), "入库 %d" % fetched]
        if data.get("dim"):
            parts.append("当前 %s %s 第 %s 页"
                         % (dim_name(data["dim"]), data.get("dim_id"),
                            data.get("page") or 0))
        self.status_label.setText(" · ".join(parts))

    def _on_records(self, items) -> None:
        self.model.prepend(list(items))
        self.preview_info.setText("本次已采 %d 条（预览最多 500 行）"
                                  % len(self.model.rows))

    def _on_finished(self, status: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        text = {"completed": "已完成", "paused": "已暂停",
                "stopped": "已停止", "failed": "失败"}.get(status, status)
        self.status_label.setText("任务%s" % text)
        self._append_log("INFO" if status == "completed" else "WARN",
                         "任务结束：%s" % text)
        self._refresh_preview()
        self._refresh_resume()

    # ================= 预览 / 日志 =================

    def _set_preview_columns(self) -> None:
        self.model.set_columns(XF_COLUMNS if self.radio_xf.isChecked() else ESF_COLUMNS)
        self._apply_column_widths()

    def _set_esf_preview(self, is_esf: bool) -> None:
        self.model.set_columns(ESF_COLUMNS if is_esf else XF_COLUMNS)
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        if self.model.columnCount() == 0:
            return
        widths = XF_WIDTHS if self.radio_xf.isChecked() else ESF_WIDTHS
        for index, width in enumerate(widths):
            if index < self.model.columnCount():
                self.table.setColumnWidth(index, width)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _refresh_preview(self) -> None:
        city = current_city(self.city_combo)
        if not city:
            return
        biz = "xf" if self.radio_xf.isChecked() else "esf"

        def load():
            store = self.ctx.store()
            return (store.recent_xf(city["id"], 300) if biz == "xf"
                    else store.recent_esf(city["id"], 300))

        worker = FuncWorker(load)
        worker.done.connect(self._on_preview_loaded)
        worker.failed.connect(
            lambda msg: self._append_log("ERROR", "预览失败：%s" % msg))
        self.workers.append(worker)
        worker.start()

    def _on_preview_loaded(self, rows) -> None:
        self._set_preview_columns()
        self.model.set_rows(list(rows))
        self.preview_info.setText("最近 %d 条" % len(rows))

    def _append_log(self, level: str, message: str) -> None:
        color = {"ERROR": "#c0392b", "WARN": "#b9770e"}.get(level, "#33503f")
        stamp = time.strftime("%H:%M:%S")
        self.log_view.appendHtml(
            '<span style="color:#8aa197">[%s]</span> '
            '<span style="color:%s">%s</span> %s'
            % (stamp, color, level, message.replace("<", "&lt;")))

    # ================= 关闭 =================

    def shutdown(self) -> None:
        if self.runner and self.runner.isRunning():
            self.runner.request_stop(False)
            self.runner.wait(3000)
        for worker in list(self.workers):
            if worker.isRunning():
                worker.wait(2000)
        self.workers.clear()
