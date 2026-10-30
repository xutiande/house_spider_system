# -*- coding: utf-8 -*-
"""后台线程：通用任务 + 采集执行器。"""

from __future__ import annotations

import random
import time
import uuid as uuidlib
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from core import parser
from core.api import AnjukeAPI, ApiError
from core.storage import MySQLStore

MAX_PAGES = 60


class FuncWorker(QThread):
    """在后台线程执行一个函数，结果通过信号回主线程。"""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            self.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class TaskRunner(QThread):
    """采集线程：领取分片 -> 逐页采集 -> 更新进度。"""

    progress = Signal(dict)
    records = Signal(object)
    log = Signal(str, str)
    finished_task = Signal(str)

    def __init__(self, api: AnjukeAPI, store: MySQLStore, task: Dict[str, Any],
                 interval_ms: int = 800, jitter_ms: int = 700):
        super().__init__()
        self.api = api
        self.store = store
        self.task = task
        self.task_id = int(task["id"])
        self.interval_ms = interval_ms
        self.jitter_ms = jitter_ms
        self._stop = False
        self._paused = False

    def request_stop(self, paused: bool = False) -> None:
        self._paused = paused
        self._stop = True

    def _sleep(self) -> None:
        delay = self.interval_ms / 1000.0 + random.uniform(0, self.jitter_ms / 1000.0)
        end = time.monotonic() + delay
        while time.monotonic() < end and not self._stop:
            time.sleep(0.05)

    def run(self) -> None:  # noqa: C901
        token = uuidlib.uuid4().hex
        biz = self.task["biz_type"]
        city_id = int(self.task["city_id"])
        keyword = self.task.get("keyword") or ""
        self.store.set_task_status(self.task_id, "running")
        self.log.emit("INFO", "任务 #%s 启动" % self.task_id)

        try:
            # 主循环：领取一个 pending 分片 -> 采完 -> 再领下一个
            while not self._stop:
                shard = self.store.claim_shard(self.task_id, token)
                if not shard:
                    # 没领到：可能别的线程在采，或者全部采完
                    progress = self.store.task_progress(self.task_id)
                    self._emit_progress(progress)
                    if progress["done"] >= progress["total"]:
                        break
                    time.sleep(0.5)
                    continue

                status = self._run_shard(shard, biz, city_id, keyword)
                if status == "stopped":
                    # 暂停/停止：分片放回队列，page_cursor 保留，下次继续
                    self.store.release_shard(int(shard["id"]))
                    break
                # done / truncated 都算该分片结束
                self.store.finish_shard(int(shard["id"]), status)
                progress = self.store.task_progress(self.task_id)
                self._emit_progress(progress)
                self.log.emit("INFO", "分片 #%s（%s %s）%s"
                              % (shard["id"], dim_name(shard["dim"]),
                                 shard["dim_id"], status))
        except ApiError as exc:
            self.log.emit("ERROR", "任务失败：%s" % exc)
            self.store.set_task_status(self.task_id, "failed")
            self.finished_task.emit("failed")
            return
        except Exception as exc:  # noqa: BLE001
            self.log.emit("ERROR", "任务异常：%r" % exc)
            self.store.set_task_status(self.task_id, "failed")
            self.finished_task.emit("failed")
            return

        if self._stop:
            # 用户主动暂停/停止：任务状态单独标记，区别于"完成"
            status = "paused" if self._paused else "stopped"
            self.store.set_task_status(self.task_id, status)
            self.log.emit("WARN", "任务%s" % ("已暂停" if self._paused else "已停止"))
            self.finished_task.emit(status)
        else:
            # 自然结束：所有分片都已处理完
            progress = self.store.task_progress(self.task_id)
            self.store.set_task_status(self.task_id, "completed")
            self.log.emit("INFO", "任务完成：分片 %d/%d，入库 %d 条"
                          % (progress["done"], progress["total"], progress["fetched"]))
            self.finished_task.emit("completed")

    def _run_shard(self, shard: Dict[str, Any], biz: str, city_id: int,
                   keyword: str) -> str:
        dim = shard["dim"]
        dim_id = int(shard["dim_id"])
        shard_keyword = shard.get("keyword") or keyword
        page = int(shard["page_cursor"] or 1)
        fetched = int(shard["fetched"] or 0)
        limit = int(shard["page_limit"] or MAX_PAGES)

        # 分片维度 -> 对应接口参数名（区/商圈/地铁线/站）
        kwargs: Dict[str, Any] = {}
        if dim == "area":
            kwargs["area_id"] = dim_id
        elif dim == "shangquan":
            kwargs["shangquan_id"] = dim_id
        elif dim == "line":
            kwargs["line_id"] = dim_id
        elif dim == "station":
            kwargs["station_id"] = dim_id

        # 从分片游标继续翻页；结束条件：没有下一页 / 到页数上限 / 收到停止
        while page <= limit:
            if self._stop:
                return "stopped"

            payload = (self.api.xf_page(city_id, page, 20, shard_keyword)
                       if biz == "xf" else
                       self.api.esf_page(city_id, page, 25, shard_keyword, **kwargs))
            if biz == "xf":
                items = parser.xf_list(payload)
                more = parser.has_more(payload, "xf")
                total = parser.total_of(payload, "xf") or 0
            else:
                items = parser.esf_list(payload)
                more = parser.has_more(payload, "esf")
                total = parser.total_of(payload, "esf") or 0

            if items:
                # 入库：唯一键去重，重复房源只更新价格/时间，不新增行
                if biz == "xf":
                    self.store.upsert_xf(items, self.task_id)
                else:
                    self.store.upsert_esf(items, self.task_id)
                fetched += len(items)
                self.records.emit(items)

            page += 1
            # 每页都落一次游标，进程被杀也能从下一页继续
            self.store.update_shard(int(shard["id"]), page, fetched, total or None)
            self._emit_progress(self.store.task_progress(self.task_id),
                                page=page - 1, fetched=fetched,
                                shard=shard, shard_total=total)

            if not more or not items:
                return "done"
            if page > MAX_PAGES:
                # 接口 60 页后数据不可信，超出的部分无法补齐
                self.log.emit("WARN", "分片 #%s 达到 60 页上限，标记截断" % shard["id"])
                return "truncated"
            self._sleep()

        if limit >= MAX_PAGES:
            self.log.emit("WARN", "分片 #%s 达到 60 页上限，标记截断" % shard["id"])
            return "truncated"
        return "done"

    def _emit_progress(self, progress: Dict[str, Any], page: int = 0,
                       fetched: int = 0, shard: Optional[Dict[str, Any]] = None,
                       shard_total: int = 0) -> None:
        self.progress.emit({
            "task_id": self.task_id,
            "dim": (shard or {}).get("dim"),
            "dim_id": (shard or {}).get("dim_id"),
            "page": page,
            "shard_total": shard_total,
            "shard_fetched": fetched,
            **progress,
        })


def dim_name(dim: str) -> str:
    return {"city": "全城", "area": "区", "shangquan": "商圈",
            "line": "地铁线", "station": "地铁站"}.get(dim, dim)
