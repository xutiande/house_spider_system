# -*- coding: utf-8 -*-
"""配置读写与对象装配（CLI / GUI 共用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .api import AnjukeAPI, ProxyPool
from .device import DeviceProfile, load_device
from .storage import MySQLStore

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"

DEFAULTS: Dict[str, Any] = {
	"mysql": {"host": "127.0.0.1", "port": 3306, "user": "root",
	          "password": "", "database": "ajk_crawl"},
	"crawler": {"qps": 3, "timeout_s": 20, "retries": 2, "interval_ms": 800,
	            "jitter_ms": 700, "page_limit": 60, "verify_ssl": True},
	"proxy": {"enabled": False, "source": "", "protocol": "http",
	          "username": "", "password": "", "check_url": "https://api.anjuke.com/",
	          "check_concurrency": 10, "check_timeout_s": 3, "max_fail": 3},
	"export": {"dir": "exports"},
}


# 加载配置
def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
	cfg = {k: dict(v) for k, v in DEFAULTS.items() if isinstance(v, dict)}
	cfg.update({k: v for k, v in DEFAULTS.items() if not isinstance(v, dict)})
	path = Path(path) if path else CONFIG_PATH
	if path.exists():
		data = yaml.safe_load(path.read_text("utf-8")) or {}
		for key, value in data.items():
			if isinstance(value, dict) and isinstance(cfg.get(key), dict):
				cfg[key].update(value)
			else:
				cfg[key] = value
	return cfg


# 保存配置
def save_config(cfg: Dict[str, Any], path: Optional[Path] = None) -> None:
	path = Path(path) if path else CONFIG_PATH
	path.parent.mkdir(parents=True, exist_ok=True)
	data = {k: cfg[k] for k in ("mysql", "crawler", "proxy", "export") if k in cfg}
	path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")


def build_api(cfg: Dict[str, Any],
              device: Optional[DeviceProfile] = None,
              refresh_device: bool = False) -> AnjukeAPI:
	device = device or load_device(refresh=refresh_device)
	proxy_cfg = cfg.get("proxy", {})
	crawler = cfg.get("crawler", {})
	pool = ProxyPool()
	if proxy_cfg.get("enabled") and proxy_cfg.get("source"):
		pool = ProxyPool.from_source(
			source=proxy_cfg.get("source", ""),
			protocol=proxy_cfg.get("protocol", "http"),
			username=proxy_cfg.get("username", ""),
			password=proxy_cfg.get("password", ""),
			check_url=proxy_cfg.get("check_url", "https://api.anjuke.com/"),
			concurrency=int(proxy_cfg.get("check_concurrency", 10)),
			timeout=float(proxy_cfg.get("check_timeout_s", 3)),
			verify=bool(crawler.get("verify_ssl", True)),
		)
	return AnjukeAPI(
		device=device,
		qps=float(crawler.get("qps", 3)),
		timeout=float(crawler.get("timeout_s", 20)),
		retries=int(crawler.get("retries", 2)),
		verify=bool(crawler.get("verify_ssl", True)),
		proxy_pool=pool,
	)


def open_store(cfg: Dict[str, Any], init: bool = True) -> MySQLStore:
	store = MySQLStore(cfg["mysql"])
	if init:
		store.init()
	return store


def test_mysql(cfg: Dict[str, Any]) -> str:
	store = MySQLStore(cfg["mysql"])
	try:
		store.init()
		with store.connect().cursor() as cur:
			cur.execute("SELECT VERSION() AS v")
			version = cur.fetchone()["v"]
		return "连接成功，MySQL %s，库 %s" % (version, store.database)
	finally:
		store.close()
