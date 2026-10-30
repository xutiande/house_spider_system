# -*- coding: utf-8 -*-
"""存储：MySQL 表结构 + 写入；以及无数据库时的 JSONL 落盘。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pymysql
from pymysql.cursors import DictCursor

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS city (
      id            INT PRIMARY KEY,
      name          VARCHAR(32) NOT NULL,
      pinyin        VARCHAR(64),
      abbr          VARCHAR(16),
      gaode_name    VARCHAR(64),
      region        VARCHAR(32),
      lng           DECIMAL(10,6),
      lat           DECIMAL(10,6),
      metro_open    TINYINT DEFAULT 0,
      esf_available TINYINT DEFAULT -1,
      esf_total     INT NULL,
      probed_at     DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS area (
      city_id  INT NOT NULL,
      area_id  INT NOT NULL,
      src_id   VARCHAR(32) COMMENT '接口1 level=2 id，仅展示',
      name     VARCHAR(64) NOT NULL,
      pinyin   VARCHAR(64),
      PRIMARY KEY (city_id, area_id),
      KEY idx_name (city_id, name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS shangquan (
      city_id      INT NOT NULL,
      shangquan_id INT NOT NULL,
      area_id      INT NOT NULL,
      name         VARCHAR(64) NOT NULL,
      PRIMARY KEY (city_id, shangquan_id),
      KEY idx_area (city_id, area_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS metro_line (
      city_id INT NOT NULL,
      line_id INT NOT NULL,
      name    VARCHAR(32) NOT NULL,
      PRIMARY KEY (city_id, line_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS metro_station (
      city_id    INT NOT NULL,
      station_id INT NOT NULL,
      line_id    INT NOT NULL,
      name       VARCHAR(64) NOT NULL,
      PRIMARY KEY (city_id, station_id),
      KEY idx_line (city_id, line_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS task (
      id           BIGINT AUTO_INCREMENT PRIMARY KEY,
      name         VARCHAR(128) NOT NULL,
      biz_type     ENUM('esf','xf') NOT NULL,
      mode         ENUM('browse','search') NOT NULL,
      city_id      INT NOT NULL,
      keyword      VARCHAR(128) DEFAULT '',
      page_limit   INT DEFAULT 10,
      concurrency  INT DEFAULT 4,
      interval_ms  INT DEFAULT 800,
      use_proxy    TINYINT DEFAULT 0,
      status       ENUM('pending','running','paused','stopped','completed','failed') DEFAULT 'pending',
      total_shards INT DEFAULT 0,
      done_shards  INT DEFAULT 0,
      created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
      started_at   DATETIME NULL,
      finished_at  DATETIME NULL,
      KEY idx_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS task_shard (
      id          BIGINT AUTO_INCREMENT PRIMARY KEY,
      task_id     BIGINT NOT NULL,
      city_id     INT NOT NULL,
      dim         ENUM('city','area','shangquan','line','station') NOT NULL,
      dim_id      INT DEFAULT 0,
      keyword     VARCHAR(128) DEFAULT '',
      page_cursor INT DEFAULT 1,
      page_limit  INT DEFAULT 60,
      est_total   INT DEFAULT -1,
      fetched     INT DEFAULT 0,
      status      ENUM('pending','running','done','truncated','failed') DEFAULT 'pending',
      worker_token VARCHAR(64) DEFAULT '',
      last_error  VARCHAR(512) DEFAULT '',
      updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      UNIQUE KEY uk_shard (task_id, dim, dim_id, keyword),
      KEY idx_claim (task_id, status, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS esf_property (
      id             BIGINT AUTO_INCREMENT PRIMARY KEY,
      house_id       BIGINT NOT NULL,
      city_id        INT NOT NULL,
      community_id   BIGINT,
      community_name VARCHAR(128),
      area_id        INT,
      area_name      VARCHAR(64),
      block_name     VARCHAR(64),
      title          VARCHAR(512),
      price_wan      DECIMAL(10,2),
      avg_price      DECIMAL(10,2),
      area           DECIMAL(8,2),
      room           TINYINT,
      hall           TINYINT,
      toilet         TINYINT,
      orient         VARCHAR(16),
      fitment        VARCHAR(32),
      floor_level    VARCHAR(64),
      house_age      VARCHAR(32),
      tags           JSON,
      highlights     JSON,
      broker_ids     JSON,
      default_photo  VARCHAR(512),
      source_url     VARCHAR(255),
      post_date      DATETIME,
      is_online      TINYINT DEFAULT 1,
      first_seen_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
      last_seen_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
      update_count   INT DEFAULT 1,
      last_task_id   BIGINT,
      UNIQUE KEY uk_house (house_id),
      KEY idx_city_price (city_id, price_wan),
      KEY idx_city_area (city_id, area_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS xf_loupan (
      id               BIGINT AUTO_INCREMENT PRIMARY KEY,
      loupan_id        BIGINT NOT NULL,
      loupan_name      VARCHAR(128),
      city_id          INT NOT NULL,
      region_id        INT,
      region_title     VARCHAR(64),
      sub_region_id    INT,
      sub_region_title VARCHAR(64),
      address          VARCHAR(255),
      property_type    VARCHAR(32),
      tags             VARCHAR(512),
      sale_status      VARCHAR(16),
      sale_title       VARCHAR(32),
      kaipan_date      VARCHAR(32),
      avg_price        DECIMAL(10,2),
      total_price      DECIMAL(10,2),
      area_range       VARCHAR(64),
      lat              DECIMAL(10,6),
      lng              DECIMAL(10,6),
      default_image    VARCHAR(512),
      detail_url       VARCHAR(255),
      first_seen_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
      last_seen_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
      last_task_id     BIGINT,
      UNIQUE KEY uk_loupan (loupan_id),
      KEY idx_city_region (city_id, region_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

ESF_COLUMNS = [
    "house_id", "city_id", "community_id", "community_name",
    "area_id", "area_name", "block_name", "title",
    "price_wan", "avg_price", "area", "room", "hall", "toilet", "orient",
    "fitment", "floor_level", "house_age", "tags", "highlights", "broker_ids",
    "default_photo", "source_url", "post_date", "is_online",
]

XF_COLUMNS = [
    "loupan_id", "loupan_name", "city_id", "region_id", "region_title",
    "sub_region_id", "sub_region_title", "address", "property_type", "tags",
    "sale_status", "sale_title", "kaipan_date", "avg_price", "total_price",
    "area_range", "lat", "lng", "default_image", "detail_url",
]


def _sql_dsn(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "host": cfg.get("host", "127.0.0.1"),
        "port": int(cfg.get("port", 3306)),
        "user": cfg.get("user", "root"),
        "password": cfg.get("password", ""),
        "charset": "utf8mb4",
        "autocommit": True,
        "connect_timeout": 5,
        "cursorclass": DictCursor,
    }


class MySQLStore:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.database = cfg.get("database", "ajk_crawl")
        self._local = threading.local()

    # ---------------- 连接 ----------------

    def connect(self) -> pymysql.connections.Connection:
        """每个线程一条连接（采集线程与 GUI 线程互不干扰）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = pymysql.connect(database=self.database, **_sql_dsn(self.cfg))
            self._local.conn = conn
        else:
            conn.ping(reconnect=True)
        return conn

    def init(self) -> None:
        """建库 + 建表（幂等）。"""
        server = pymysql.connect(**_sql_dsn(self.cfg))
        try:
            with server.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci" % self.database)
        finally:
            server.close()

        conn = self.connect()
        with conn.cursor() as cur:
            for ddl in SCHEMA:
                cur.execute(ddl)
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """旧库平滑升级：缺列就补，不删数据。"""
        wanted = {
            "esf_property": {
                "area_id": "INT",
                "area_name": "VARCHAR(64)",
                "block_name": "VARCHAR(64)",
            },
        }
        conn = self.connect()
        with conn.cursor() as cur:
            for table, cols in wanted.items():
                cur.execute(
                    "SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (self.database, table))
                have = {row["c"].lower() for row in cur.fetchall()}
                for col, ddl in cols.items():
                    if col.lower() not in have:
                        cur.execute("ALTER TABLE `%s` ADD COLUMN `%s` %s"
                                    % (table, col, ddl))

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    # ---------------- 元数据 ----------------

    def save_cities(self, cities: Iterable[Dict[str, Any]]) -> int:
        rows = [(
            c["id"], c["name"], c.get("pinyin"), c.get("abbr"),
            c.get("gaode_name"), c.get("region"), c.get("lng"), c.get("lat"),
            c.get("metro_open", 0), c.get("esf_available", -1),
            c.get("esf_total"), c.get("probed_at"),
        ) for c in cities]
        sql = """
            INSERT INTO city (id, name, pinyin, abbr, gaode_name, region, lng, lat,
                              metro_open, esf_available, esf_total, probed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE name=VALUES(name), pinyin=VALUES(pinyin),
              abbr=VALUES(abbr), gaode_name=VALUES(gaode_name), region=VALUES(region),
              lng=VALUES(lng), lat=VALUES(lat), metro_open=VALUES(metro_open),
              esf_available=VALUES(esf_available), esf_total=VALUES(esf_total),
              probed_at=VALUES(probed_at)
        """
        with self.connect().cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def save_area_filters(self, city_id: int, filters: List[Dict[str, Any]]) -> tuple:
        area_rows, shop_rows = [], []
        for item in filters:
            area_rows.append((city_id, item["area_id"], None,
                              item["name"], item.get("pinyin")))
            for sq in item.get("shangquan") or []:
                shop_rows.append((city_id, sq["shangquan_id"], item["area_id"],
                                  sq["name"]))
        conn = self.connect()
        with conn.cursor() as cur:
            if area_rows:
                cur.executemany(
                    "INSERT INTO area (city_id, area_id, src_id, name, pinyin) "
                    "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                    "name=VALUES(name), pinyin=VALUES(pinyin)", area_rows)
            if shop_rows:
                cur.executemany(
                    "INSERT INTO shangquan (city_id, shangquan_id, area_id, name) "
                    "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                    "area_id=VALUES(area_id), name=VALUES(name)", shop_rows)
        return len(area_rows), len(shop_rows)

    def save_city_meta(self, city_id: int, meta: Dict[str, List[Dict[str, Any]]]) -> None:
        lines = [(city_id, x["line_id"], x["name"]) for x in meta.get("lines", [])]
        stations = [(city_id, x["station_id"], x["line_id"], x["name"])
                    for x in meta.get("stations", [])]
        conn = self.connect()
        with conn.cursor() as cur:
            if lines:
                cur.executemany(
                    "INSERT INTO metro_line (city_id, line_id, name) VALUES (%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE name=VALUES(name)", lines)
            if stations:
                cur.executemany(
                    "INSERT INTO metro_station (city_id, station_id, line_id, name) "
                    "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                    "line_id=VALUES(line_id), name=VALUES(name)", stations)
            # 把接口1 的区 id 回填到 area.src_id（按名称匹配）
            for area in meta.get("areas", []):
                if area.get("level") != 2:
                    continue
                cur.execute(
                    "UPDATE area SET src_id=%s WHERE city_id=%s AND name=%s",
                    (str(area["area_id"]), city_id, area["name"]))

    # ---------------- 业务数据 ----------------

    def upsert_esf(self, records: List[Dict[str, Any]], task_id: Optional[int] = None) -> int:
        """二手房入库：house_id 冲突时只更新可变字段，不新增行。"""
        if not records:
            return 0
        rows = []
        for r in records:
            rows.append(tuple(r.get(c) for c in ESF_COLUMNS) +
                        (task_id,))
        cols = ", ".join(ESF_COLUMNS) + ", last_task_id"
        holders = ", ".join(["%s"] * (len(ESF_COLUMNS) + 1))
        updates = ", ".join("%s=VALUES(%s)" % (c, c) for c in ESF_COLUMNS
                            if c not in ("house_id", "city_id"))
        sql = ("INSERT INTO esf_property (%s) VALUES (%s) ON DUPLICATE KEY UPDATE "
               "%s, last_seen_at=NOW(), update_count=update_count+1" %
               (cols, holders, updates))
        with self.connect().cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def upsert_xf(self, records: List[Dict[str, Any]], task_id: Optional[int] = None) -> int:
        if not records:
            return 0
        rows = [tuple(r.get(c) for c in XF_COLUMNS) + (task_id,) for r in records]
        cols = ", ".join(XF_COLUMNS) + ", last_task_id"
        holders = ", ".join(["%s"] * (len(XF_COLUMNS) + 1))
        updates = ", ".join("%s=VALUES(%s)" % (c, c) for c in XF_COLUMNS
                            if c not in ("loupan_id", "city_id"))
        sql = ("INSERT INTO xf_loupan (%s) VALUES (%s) ON DUPLICATE KEY UPDATE "
               "%s, last_seen_at=NOW()" % (cols, holders, updates))
        with self.connect().cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def count(self, table: str, city_id: Optional[int] = None) -> int:
        if table not in ("esf_property", "xf_loupan"):
            raise ValueError("unsupported table: %s" % table)
        sql = "SELECT COUNT(*) AS n FROM %s" % table
        args: tuple = ()
        if city_id is not None:
            sql += " WHERE city_id=%s"
            args = (city_id,)
        with self.connect().cursor() as cur:
            cur.execute(sql, args)
            return int(cur.fetchone()["n"])

    def fetch_areas(self, city_id: int) -> List[Dict[str, Any]]:
        with self.connect().cursor() as cur:
            cur.execute("SELECT area_id, src_id, name FROM area WHERE city_id=%s "
                        "ORDER BY area_id", (city_id,))
            return list(cur.fetchall())


    # ---------------- 任务 / 分片 ----------------

    def create_task(self, name: str, biz_type: str, mode: str, city_id: int,
                    keyword: str = "", page_limit: int = 10, concurrency: int = 4,
                    interval_ms: int = 800, use_proxy: int = 0) -> int:
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO task (name, biz_type, mode, city_id, keyword, page_limit, "
                "concurrency, interval_ms, use_proxy, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (name, biz_type, mode, city_id, keyword, page_limit,
                 concurrency, interval_ms, use_proxy))
            return int(cur.lastrowid)

    def add_shards(self, task_id: int, shards: List[Dict[str, Any]]) -> int:
        if not shards:
            return 0
        rows = [(task_id, s["city_id"], s["dim"], int(s.get("dim_id", 0)),
                 s.get("keyword", ""), int(s.get("est_total", -1)),
                 int(s.get("page_limit", 60))) for s in shards]
        conn = self.connect()
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO task_shard (task_id, city_id, dim, dim_id, keyword, "
                "est_total, page_limit) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE est_total=VALUES(est_total), "
                "page_limit=VALUES(page_limit)", rows)
            cur.execute("UPDATE task SET total_shards=("
                        "SELECT COUNT(*) FROM task_shard WHERE task_id=%s) WHERE id=%s",
                        (task_id, task_id))
        return len(rows)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self.connect().cursor() as cur:
            cur.execute("SELECT * FROM task WHERE id=%s", (task_id,))
            return cur.fetchone()

    def unfinished_task(self, city_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """最近一个可继续的任务（暂停/停止/未启动）。"""
        sql = ("SELECT * FROM task WHERE status IN ('paused','stopped','pending')")
        args: List[Any] = []
        if city_id is not None:
            sql += " AND city_id=%s"
            args.append(city_id)
        sql += " ORDER BY id DESC LIMIT 1"
        with self.connect().cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchone()

    def set_task_status(self, task_id: int, status: str) -> None:
        sets = "status=%s"
        args: List[Any] = [status, task_id]
        if status == "running":
            sets += ", started_at=IFNULL(started_at, NOW())"
        if status in ("completed", "failed", "stopped"):
            sets += ", finished_at=NOW()"
        with self.connect().cursor() as cur:
            cur.execute("UPDATE task SET %s WHERE id=%%s" % sets, args)

    def reset_running_shards(self) -> int:
        """把所有 running 分片放回队列（慎用，可能影响并行实例）。"""
        with self.connect().cursor() as cur:
            return cur.execute(
                "UPDATE task_shard SET status='pending', worker_token='' "
                "WHERE status='running'")

    def recover_interrupted(self, stale_minutes: int = 10) -> int:
        """启动时恢复上次异常退出遗留的任务。

        - 超过 stale_minutes 仍是 running 的分片 -> pending（保留游标）
        - 已经没有 running 分片的 running 任务 -> paused（可点"继续上次"）
        """
        changed = 0
        conn = self.connect()
        with conn.cursor() as cur:
            changed = cur.execute(
                "UPDATE task_shard SET status='pending', worker_token='' "
                "WHERE status='running' AND updated_at < NOW() - INTERVAL %s MINUTE",
                (int(stale_minutes),))
            cur.execute(
                "UPDATE task SET status='paused' "
                "WHERE status='running' AND started_at < NOW() - INTERVAL %s MINUTE "
                "AND id NOT IN (SELECT task_id FROM ("
                "  SELECT DISTINCT task_id FROM task_shard WHERE status='running'"
                ") AS running_shards)",
                (int(stale_minutes),))
        return changed

    def claim_shard(self, task_id: int, token: str) -> Optional[Dict[str, Any]]:
        """原子领取一个分片（MySQL 5.7 没有 SKIP LOCKED，用 token 两段式）。

        1) UPDATE ... ORDER BY id LIMIT 1：并发下每条只会命中一行；
        2) 再按 token 把自己刚占的那行读回来。
        """
        conn = self.connect()
        with conn.cursor() as cur:
            affected = cur.execute(
                "UPDATE task_shard SET status='running', worker_token=%s, "
                "updated_at=NOW() WHERE task_id=%s AND status='pending' "
                "ORDER BY id LIMIT 1", (token, task_id))
            if not affected:
                return None
            cur.execute(
                "SELECT * FROM task_shard WHERE task_id=%s AND worker_token=%s "
                "AND status='running' LIMIT 1", (task_id, token))
            return cur.fetchone()

    def update_shard(self, shard_id: int, page_cursor: int, fetched: int,
                     est_total: Optional[int] = None) -> None:
        with self.connect().cursor() as cur:
            if est_total is None:
                cur.execute("UPDATE task_shard SET page_cursor=%s, fetched=%s, "
                            "updated_at=NOW() WHERE id=%s",
                            (page_cursor, fetched, shard_id))
            else:
                cur.execute("UPDATE task_shard SET page_cursor=%s, fetched=%s, "
                            "est_total=%s, updated_at=NOW() WHERE id=%s",
                            (page_cursor, fetched, est_total, shard_id))

    def finish_shard(self, shard_id: int, status: str = "done",
                     error: str = "") -> None:
        with self.connect().cursor() as cur:
            cur.execute("UPDATE task_shard SET status=%s, worker_token='', "
                        "last_error=%s, updated_at=NOW() WHERE id=%s",
                        (status, error[:500], shard_id))

    def release_shard(self, shard_id: int) -> None:
        """停止任务时把未采完的分片放回队列，保留 page_cursor。"""
        with self.connect().cursor() as cur:
            cur.execute("UPDATE task_shard SET status='pending', worker_token='' "
                        "WHERE id=%s", (shard_id,))

    def task_progress(self, task_id: int) -> Dict[str, int]:
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COALESCE(SUM(status IN ('done','truncated','failed')),0) AS done, "
                "COALESCE(SUM(fetched),0) AS fetched "
                "FROM task_shard WHERE task_id=%s", (task_id,))
            row = cur.fetchone()
            cur.execute("UPDATE task SET done_shards=%s WHERE id=%s",
                        (int(row["done"]), task_id))
            cur.execute("SELECT status FROM task WHERE id=%s", (task_id,))
            status = (cur.fetchone() or {}).get("status")
            if status == "running" and int(row["done"]) >= int(row["total"]) > 0:
                cur.execute("UPDATE task SET status='completed', finished_at=NOW() "
                            "WHERE id=%s", (task_id,))
                status = "completed"
        return {"total": int(row["total"]), "done": int(row["done"]),
                "fetched": int(row["fetched"]), "status": status}

    # ---------------- 预览 / 导出 ----------------

    def recent_esf(self, city_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        sql = ("SELECT house_id, community_name, area_name, block_name, title, "
               "price_wan, avg_price, area, room, hall, floor_level, orient, "
               "fitment, house_age, source_url, post_date, last_seen_at "
               "FROM esf_property")
        args: List[Any] = []
        if city_id is not None:
            sql += " WHERE city_id=%s"
            args.append(city_id)
        sql += " ORDER BY last_seen_at DESC LIMIT %s"
        args.append(int(limit))
        with self.connect().cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    def recent_xf(self, city_id: Optional[int] = None, limit: int = 100) -> List[Dict[str, Any]]:
        sql = ("SELECT loupan_id, loupan_name, region_title, sub_region_title, "
               "address, property_type, sale_title, avg_price, total_price, "
               "area_range, detail_url, last_seen_at FROM xf_loupan")
        args: List[Any] = []
        if city_id is not None:
            sql += " WHERE city_id=%s"
            args.append(city_id)
        sql += " ORDER BY last_seen_at DESC LIMIT %s"
        args.append(int(limit))
        with self.connect().cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    def area_counts(self, city_id: int) -> List[Dict[str, Any]]:
        with self.connect().cursor() as cur:
            cur.execute(
                "SELECT COALESCE(area_name,'(未知)') AS name, COUNT(*) AS n "
                "FROM esf_property WHERE city_id=%s GROUP BY area_name "
                "ORDER BY n DESC", (city_id,))
            return list(cur.fetchall())

    def region_counts(self, city_id: int) -> List[Dict[str, Any]]:
        with self.connect().cursor() as cur:
            cur.execute(
                "SELECT COALESCE(region_title,'(未知)') AS name, COUNT(*) AS n "
                "FROM xf_loupan WHERE city_id=%s GROUP BY region_title "
                "ORDER BY n DESC", (city_id,))
            return list(cur.fetchall())

    def export_esf_csv(self, city_id: int, path: str, area_name: str = "",
                       batch: int = 5000) -> int:
        import csv
        headers = ["房源ID", "小区", "区域", "商圈", "标题", "总价(万)", "单价(元/㎡)",
                   "面积(㎡)", "室", "厅", "楼层", "朝向", "装修", "房龄", "链接", "发布时间"]
        total = 0
        last_id = 0
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 按 id 游标分批读取，避免大表一次性进内存；utf-8-sig 让 Excel 正常识别中文
        with open(path, "w", encoding="utf-8-sig", newline="") as fh, \
                self.connect().cursor() as cur:
            writer = csv.writer(fh)
            writer.writerow(headers)
            while True:
                sql = ("SELECT id, house_id, community_name, area_name, block_name, "
                       "title, price_wan, avg_price, area, room, hall, floor_level, "
                       "orient, fitment, house_age, source_url, post_date "
                       "FROM esf_property WHERE city_id=%s AND id>%s")
                args: List[Any] = [city_id, last_id]
                if area_name:
                    sql += " AND area_name=%s"
                    args.append(area_name)
                sql += " ORDER BY id LIMIT %s"
                args.append(batch)
                cur.execute(sql, args)
                rows = cur.fetchall()
                if not rows:
                    break
                for r in rows:
                    writer.writerow([
                        r["house_id"], r["community_name"], r["area_name"],
                        r["block_name"], r["title"], r["price_wan"], r["avg_price"],
                        r["area"], r["room"], r["hall"], r["floor_level"],
                        r["orient"], r["fitment"], r["house_age"], r["source_url"],
                        r["post_date"],
                    ])
                last_id = rows[-1]["id"]
                total += len(rows)
        return total

    def export_xf_csv(self, city_id: int, path: str, region_title: str = "",
                      batch: int = 5000) -> int:
        import csv
        headers = ["楼盘ID", "楼盘名", "区域", "片区", "地址", "物业类型", "销售状态",
                   "均价(元/㎡)", "总价(万)", "面积", "详情链接"]
        total = 0
        last_id = 0
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 按 id 游标分批读取，避免大表一次性进内存；utf-8-sig 让 Excel 正常识别中文
        with open(path, "w", encoding="utf-8-sig", newline="") as fh, \
                self.connect().cursor() as cur:
            writer = csv.writer(fh)
            writer.writerow(headers)
            while True:
                sql = ("SELECT id, loupan_id, loupan_name, region_title, "
                       "sub_region_title, address, property_type, sale_title, "
                       "avg_price, total_price, area_range, detail_url "
                       "FROM xf_loupan WHERE city_id=%s AND id>%s")
                args: List[Any] = [city_id, last_id]
                if region_title:
                    sql += " AND region_title=%s"
                    args.append(region_title)
                sql += " ORDER BY id LIMIT %s"
                args.append(batch)
                cur.execute(sql, args)
                rows = cur.fetchall()
                if not rows:
                    break
                for r in rows:
                    writer.writerow([
                        r["loupan_id"], r["loupan_name"], r["region_title"],
                        r["sub_region_title"], r["address"], r["property_type"],
                        r["sale_title"], r["avg_price"], r["total_price"],
                        r["area_range"], r["detail_url"],
                    ])
                last_id = rows[-1]["id"]
                total += len(rows)
        return total


class JsonlStore:
    """无数据库时的落盘方式：每行一条记录。"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        with self.path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return len(records)
