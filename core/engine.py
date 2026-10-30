# -*- coding: utf-8 -*-
"""任务构建：把"城市 + 勾选地点"展开成可执行的分片。

这里不依赖 GUI，CLI 与界面共用。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import parser
from .api import AnjukeAPI, ApiError
from .storage import MySQLStore

MAX_PAGES = 60            # 二手房深度翻页上限
PAGE_SPLIT_LIMIT = 1500   # 超过就下钻


class TaskBuilder:
    def __init__(self, api: AnjukeAPI, store: MySQLStore,
                 log: Optional[Callable[[str], None]] = None):
        self.api = api
        self.store = store
        self.log = log or (lambda msg: None)

    # ---------------- 探针 ----------------

    def probe_esf(self, city_id: int, keyword: str = "",
                  area_id: Optional[int] = None,
                  shangquan_id: Optional[int] = None,
                  line_id: Optional[int] = None,
                  station_id: Optional[int] = None) -> int:
        try:
            payload = self.api.esf_page(
                city_id, 1, 25, keyword,
                area_id=area_id, shangquan_id=shangquan_id,
                line_id=line_id, station_id=station_id)
            return parser.total_of(payload, "esf") or 0
        except ApiError as exc:
            self.log("[warn] 探针失败：%s" % exc)
            return 0

    def probe_xf(self, city_id: int, keyword: str = "") -> int:
        try:
            payload = self.api.xf_page(city_id, 1, 20, keyword)
            return parser.total_of(payload, "xf") or 0
        except ApiError as exc:
            self.log("[warn] 新房探针失败：%s" % exc)
            return 0

    # ---------------- 元数据 ----------------

    def ensure_areas(self, city_id: int
                     ) -> Tuple[List[Dict[str, Any]], Dict[int, List[Dict[str, Any]]]]:
        """返回 (区列表, 区id -> 商圈列表)，优先用库里的。"""
        areas_map: Dict[int, List[Dict[str, Any]]] = {}
        rows = self.store.fetch_areas(city_id)
        if rows:
            with self.store.connect().cursor() as cur:
                cur.execute("SELECT area_id, shangquan_id, name FROM shangquan "
                            "WHERE city_id=%s ORDER BY shangquan_id", (city_id,))
                for row in cur.fetchall():
                    areas_map.setdefault(int(row["area_id"]), []).append(
                        {"shangquan_id": int(row["shangquan_id"]), "name": row["name"]})
            return rows, areas_map

        self.log("库里没有该城市的地点数据，先从接口拉取…")
        filters = parser.parse_area_filters(self.api.area_filters(city_id))
        self.store.save_area_filters(city_id, filters)
        for item in filters:
            areas_map[item["area_id"]] = item["shangquan"]
        return [{"area_id": a["area_id"], "name": a["name"]} for a in filters], areas_map

    # ---------------- 展开 ----------------

    def expand(self, city_id: int, biz: str, mode: str, keyword: str,
               selections: List[Dict[str, Any]],
               page_limit: int = 60) -> List[Dict[str, Any]]:
        """把勾选条件展开成可执行的 query 分片。

        规则：
        - 新房：只有一个全城分片（新房区域 id 与二手房/接口1 不通用）。
        - 指定页数（<60）：不下钻，一个勾选 = 一个分片，只采前 N 页。
        - 全量：先探针总额；>1500 条就按区下钻，区仍 >1500 再按商圈拆。
        """
        if not selections:
            selections = [{"dim": "city", "dim_id": 0, "name": "全城"}]

        if biz == "xf":
            # 新房：page_size 固定 20，最多约 75 页
            total = self.probe_xf(city_id, keyword)
            pages = max(1, min(75, math.ceil(total / 20))) if total else 1
            self.log("新房：total=%s，约 %d 页" % (total, pages))
            return [{"city_id": city_id, "dim": "city", "dim_id": 0,
                     "keyword": keyword, "est_total": total,
                     "page_limit": min(pages, page_limit or pages)}]

        areas, areas_map = self.ensure_areas(city_id)
        shards: List[Dict[str, Any]] = []

        # 只采前 N 页时不做下钻：用户要的是"这个条件下的前 N 页"
        if page_limit and page_limit < MAX_PAGES:
            for sel in selections:
                dim = sel["dim"]
                dim_id = int(sel.get("dim_id") or 0)
                total = self._probe_for(dim, city_id, dim_id, keyword)
                shards.append({
                    "city_id": city_id, "dim": dim, "dim_id": dim_id,
                    "keyword": keyword, "est_total": total,
                    "page_limit": page_limit,
                })
            self.log("前 %d 页模式：%d 个分片（不下钻）" % (page_limit, len(shards)))
            return shards

        for sel in selections:
            dim = sel["dim"]
            dim_id = int(sel.get("dim_id") or 0)
            name = sel.get("name") or dim

            if dim == "city":
                # 全城先探针；超过分片阈值就按区拆，否则一个分片搞定
                total = self.probe_esf(city_id, keyword)
                self.log("全城 total=%s" % total)
                if total <= PAGE_SPLIT_LIMIT:
                    shards.append(self._shard(city_id, dim, 0, keyword, total, page_limit))
                    continue
                for area in areas:
                    aid = int(area["area_id"])
                    area_total = self.probe_esf(city_id, keyword, area_id=aid)
                    self._expand_area(city_id, aid, area["name"], keyword,
                                      area_total, page_limit, areas_map, shards)
            elif dim == "area":
                total = self.probe_esf(city_id, keyword, area_id=dim_id)
                self._expand_area(city_id, dim_id, name, keyword, total,
                                  page_limit, areas_map, shards)
            elif dim == "shangquan":
                total = self.probe_esf(city_id, keyword, shangquan_id=dim_id)
                shards.append(self._shard(city_id, dim, dim_id, keyword, total, page_limit))
            elif dim == "line":
                total = self.probe_esf(city_id, keyword, line_id=dim_id)
                shards.append(self._shard(city_id, dim, dim_id, keyword, total, page_limit))
            elif dim == "station":
                total = self.probe_esf(city_id, keyword, station_id=dim_id)
                shards.append(self._shard(city_id, dim, dim_id, keyword, total, page_limit))

        unique: Dict[Tuple[str, int, str], Dict[str, Any]] = {}
        for shard in shards:
            unique[(shard["dim"], shard["dim_id"], shard["keyword"])] = shard
        result = list(unique.values())
        self.log("展开完成：%d 个分片" % len(result))
        return result

    def _probe_for(self, dim: str, city_id: int, dim_id: int, keyword: str) -> int:
        if dim == "area":
            return self.probe_esf(city_id, keyword, area_id=dim_id)
        if dim == "shangquan":
            return self.probe_esf(city_id, keyword, shangquan_id=dim_id)
        if dim == "line":
            return self.probe_esf(city_id, keyword, line_id=dim_id)
        if dim == "station":
            return self.probe_esf(city_id, keyword, station_id=dim_id)
        return self.probe_esf(city_id, keyword)

    def _expand_area(self, city_id: int, area_id: int, area_name: str,
                     keyword: str, total: int, page_limit: int,
                     areas_map: Dict[int, List[Dict[str, Any]]],
                     out: List[Dict[str, Any]]) -> None:
        if total <= PAGE_SPLIT_LIMIT:
            out.append(self._shard(city_id, "area", area_id, keyword, total, page_limit))
            return
        shops = areas_map.get(area_id) or []
        if not shops:
            out.append(self._shard(city_id, "area", area_id, keyword, total, page_limit))
            return
        self.log("%s total=%s，按 %d 个商圈拆分" % (area_name, total, len(shops)))
        for sq in shops:
            out.append(self._shard(city_id, "shangquan", int(sq["shangquan_id"]),
                                   keyword, -1, page_limit))

    @staticmethod
    def _shard(city_id: int, dim: str, dim_id: int, keyword: str,
               total: int, page_limit: int) -> Dict[str, Any]:
        pages = max(1, min(MAX_PAGES, math.ceil(total / 25))) if total > 0 else MAX_PAGES
        return {
            "city_id": city_id,
            "dim": dim,
            "dim_id": dim_id,
            "keyword": keyword,
            "est_total": total,
            "page_limit": min(pages, page_limit) if page_limit else pages,
        }
