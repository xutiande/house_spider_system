# -*- coding: utf-8 -*-
"""响应解析：接口原始 JSON -> 入库记录。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_dt(value: Any) -> Optional[datetime]:
    ts = _to_int(value)
    if not ts or ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        return None


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# 二手房
# ---------------------------------------------------------------------------

def parse_esf_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """列表项 -> esf_property 记录；广告/推荐卡片返回 None。"""
    if not isinstance(item, dict):
        return None
    info = item.get("info")
    if not isinstance(info, dict):
        return None
    prop = info.get("property")
    if not isinstance(prop, dict):
        return None
    base = prop.get("base")
    if not isinstance(base, dict) or not base:
        return None

    attr = base.get("attribute") if isinstance(base.get("attribute"), dict) else {}
    community = {}
    cb = info.get("community")
    if isinstance(cb, dict) and isinstance(cb.get("base"), dict):
        community = cb["base"]

    labels = base.get("labels")
    tags = [x.get("label") for x in labels
            if isinstance(x, dict) and x.get("label")] if isinstance(labels, list) else []
    if not tags:
        tags = [x for x in _list(base.get("highlights")) if isinstance(x, str)]

    return {
        "house_id": _to_int(base.get("house_id") or base.get("id")),
        "city_id": _to_int(base.get("city_id")),
        "community_id": _to_int(base.get("community_id")),
        "community_name": community.get("name"),
        "area_id": _to_int(community.get("areaId")),
        "area_name": community.get("areaName"),
        "block_name": community.get("blockName"),
        "title": base.get("title"),
        "price_wan": _to_float(attr.get("price")),
        "avg_price": _to_float(attr.get("avg_price")),
        "area": _to_float(attr.get("area_num")),
        "room": _to_int(attr.get("room_num")),
        "hall": _to_int(attr.get("hall_num")),
        "toilet": _to_int(attr.get("toilet_num")),
        "orient": attr.get("orient"),
        "fitment": attr.get("fitment_name"),
        "floor_level": attr.get("floor_level"),
        "house_age": attr.get("house_age"),
        "tags": json.dumps(tags, ensure_ascii=False) if tags else None,
        "highlights": json.dumps(_list(base.get("highlights")), ensure_ascii=False),
        "broker_ids": json.dumps(_list(base.get("broker_ids")), ensure_ascii=False),
        "default_photo": base.get("default_photo"),
        "source_url": base.get("tw_url"),
        "post_date": _to_dt(base.get("post_date")),
        "is_online": 1 if str(base.get("is_online", "1")) == "1" else 0,
    }


# ---------------------------------------------------------------------------
# 新房
# ---------------------------------------------------------------------------

def parse_xf_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    loupan_id = _to_int(row.get("loupan_id"))
    if not loupan_id:
        return None

    detail = row.get("loupan_detail") if isinstance(row.get("loupan_detail"), dict) else {}
    price = detail.get("price") if isinstance(detail.get("price"), dict) else {}

    return {
        "loupan_id": loupan_id,
        "loupan_name": row.get("loupan_name"),
        "city_id": _to_int(row.get("city_id")),
        "region_id": _to_int(row.get("region_id")),
        "region_title": row.get("region_title"),
        "sub_region_id": _to_int(row.get("sub_region_id")),
        "sub_region_title": row.get("sub_region_title"),
        "address": row.get("address"),
        "property_type": row.get("loupan_property_type"),
        "tags": row.get("tags"),
        "sale_status": row.get("status_sale"),
        "sale_title": row.get("sale_title"),
        "kaipan_date": row.get("kaipan_new_date"),
        "avg_price": _to_float(row.get("new_price_value") or price.get("avg_price_value")),
        "total_price": _to_float(price.get("total_price_value")),
        "area_range": row.get("area_range"),
        "lat": _to_float(row.get("lat")),
        "lng": _to_float(row.get("lng")),
        "default_image": row.get("default_image"),
        "detail_url": row.get("touch_loupan_view"),
    }


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------

def parse_area_filters(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """findprop/filter -> [{area_id, name, shangquan:[{shangquan_id,name}]}]"""
    filters = ((payload.get("data") or {}).get("filters") or {})
    regions = filters.get("regions") or []
    result = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        area_id = _to_int(region.get("typeid"))
        if not area_id:
            continue
        shops = []
        for sq in region.get("shangquan") or []:
            if not isinstance(sq, dict):
                continue
            sq_id = _to_int(sq.get("typeid"))
            if not sq_id:
                continue
            shops.append({"shangquan_id": sq_id, "name": sq.get("name") or ""})
        result.append({
            "area_id": area_id,
            "name": region.get("name") or "",
            "pinyin": region.get("pinyin") or "",
            "shangquan": shops,
        })
    return result


def parse_city_meta(payload: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """接口1 -> {areas, lines, stations}。"""
    result = (payload.get("result") or {})
    areas, lines, stations = [], [], []
    for item in result.get("area") or []:
        if not isinstance(item, dict):
            continue
        aid = _to_int(item.get("id"))
        if not aid:
            continue
        areas.append({
            "area_id": aid,
            "pid": _to_int(item.get("pid")),
            "name": item.get("name") or "",
            "pinyin": item.get("pinyin") or "",
            "level": _to_int(item.get("level")),
        })
    for item in result.get("subway") or []:
        if not isinstance(item, dict):
            continue
        sid = _to_int(item.get("id"))
        if not sid:
            continue
        level = _to_int(item.get("level"))
        if level == 2:
            lines.append({"line_id": sid, "name": item.get("name") or ""})
        else:
            stations.append({
                "station_id": sid,
                "line_id": _to_int(item.get("pid")),
                "name": item.get("name") or "",
            })
    return {"areas": areas, "lines": lines, "stations": stations}


def esf_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data") or {}
    items = data.get("list") or []
    return [r for r in (parse_esf_item(i) for i in items) if r]


def xf_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = ((payload.get("result") or {}).get("rows") or [])
    return [r for r in (parse_xf_row(i) for i in rows) if r]


def total_of(payload: Dict[str, Any], biz: str = "esf") -> Optional[int]:
    if biz == "xf":
        return _to_int((payload.get("result") or {}).get("total"))
    return _to_int((payload.get("data") or {}).get("total"))


def has_more(payload: Dict[str, Any], biz: str = "esf") -> bool:
    if biz == "xf":
        total = total_of(payload, "xf") or 0
        rows = len(((payload.get("result") or {}).get("rows") or []))
        page = _to_int(((payload.get("result") or {}).get("params") or {}).get("page")) or 1
        size = _to_int(((payload.get("result") or {}).get("params") or {}).get("page_size")) or 20
        return page * size < total and rows > 0
    data = payload.get("data") or {}
    return str(data.get("has_more")) == "1" and bool(data.get("list"))
