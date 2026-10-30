# -*- coding: utf-8 -*-
"""接口封装：签名、限速、重试、代理、四个接口。"""

from __future__ import annotations

import random
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .device import DeviceProfile
from .sign import make_nsign

API_HOST = "https://api.anjuke.com"
META_HOST = "https://apirent.anjuke.com"

PATH_ESF = "/mobile/v5/sale/property/list"
PATH_AREA_FILTER = "/mobile/v5/sale/property/findprop/filter"
PATH_XF = "/xinfang/m/android/1.3/loupan/newlistv2/"
PATH_CITY_META = "/gongyu/comment/Get_all_area_subway"

UA = "a-ajk/17.43.1/Android-RMX2202/android/14"


class ApiError(RuntimeError):
	def __init__(self, message: str, http_status: int = 0, payload: Optional[dict] = None):
		super().__init__(message)
		self.http_status = http_status
		self.payload = payload or {}


class RateLimiter:
	"""进程内令牌桶，所有线程共享。"""

	def __init__(self, qps: float):
		self.rate = max(0.1, float(qps))
		self.capacity = max(1.0, self.rate)
		self.tokens = self.capacity
		self.ts = time.monotonic()
		self.lock = threading.Lock()

	def wait(self) -> None:
		while True:
			with self.lock:
				now = time.monotonic()
				self.tokens = min(self.capacity, self.tokens + (now - self.ts) * self.rate)
				self.ts = now
				if self.tokens >= 1:
					self.tokens -= 1
					return
				need = (1 - self.tokens) / self.rate
			time.sleep(min(max(need, 0.01), 1.0))


class ProxyPool:
	"""代理列表：从文件 / URL 读取 ip:port，启动时校验，失败剔除。

	不做持久化、不做监控，仅在内存中轮询。
	"""

	def __init__(self, urls: Optional[Iterable[str]] = None):
		self._items: List[Dict[str, Any]] = [{"url": u.rstrip("/"), "fails": 0}
											 for u in (urls or [])]
		self._lock = threading.Lock()
		self._idx = 0

	@property
	def available(self) -> int:
		with self._lock:
			return len(self._items)

	@classmethod
	def from_source(
		cls,
		source: str,
		protocol: str = "http",
		username: str = "",
		password: str = "",
		check_url: str = API_HOST,
		concurrency: int = 10,
		timeout: float = 3.0,
		verify: bool = True,
	) -> "ProxyPool":
		if not source:
			return cls()
		lines = cls._read_lines(source, timeout=max(timeout, 5.0))
		urls = [u for u in (cls._normalize(line, protocol, username, password)
							for line in lines) if u]
		if not urls:
			print("[proxy] 来源为空或格式不合法：%s" % source)
			return cls()

		alive = cls._validate(urls, check_url, concurrency, timeout, verify)
		print("[proxy] 校验完成：%d/%d 可用" % (len(alive), len(urls)))
		return cls(alive)

	@staticmethod
	def _read_lines(source: str, timeout: float) -> List[str]:
		if source.startswith(("http://", "https://")):
			resp = requests.get(source, timeout=timeout)
			resp.raise_for_status()
			text = resp.text
		else:
			text = Path(source).read_text("utf-8", errors="ignore")
		return [ln.strip() for ln in text.splitlines()
				if ln.strip() and not ln.strip().startswith("#")]

	@staticmethod
	def _normalize(line: str, protocol: str, username: str, password: str) -> Optional[str]:
		line = line.strip()
		if "://" not in line:
			line = "%s://%s" % (protocol, line)
		parts = line.split("://", 1)
		scheme, rest = parts[0], parts[1]
		if "@" not in rest and username and password and rest.count(":") == 1:
			rest = "%s:%s@%s" % (username, password, rest)
		# 兼容 ip:port:user:pass
		bits = rest.split(":")
		if "@" not in rest and len(bits) == 4:
			host, port, user, pwd = bits
			rest = "%s:%s@%s:%s" % (user, pwd, host, port)
		if ":" not in rest.rstrip("/").split("@")[-1]:
			return None
		return "%s://%s" % (scheme, rest)

	@staticmethod
	def _validate(urls: List[str], check_url: str, concurrency: int,
				  timeout: float, verify: bool) -> List[str]:
		def check(url: str) -> Optional[str]:
			try:
				resp = requests.get(check_url, proxies={"http": url, "https": url},
									timeout=timeout, verify=verify)
				return url if resp.status_code < 500 else None
			except Exception:
				return None

		with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
			return [u for u in pool.map(check, urls) if u]

	def get(self) -> Optional[Dict[str, str]]:
		with self._lock:
			if not self._items:
				return None
			item = self._items[self._idx % len(self._items)]
			self._idx += 1
		return {"http": item["url"], "https": item["url"]}

	def fail(self, proxies: Optional[Dict[str, str]], max_fail: int = 3) -> None:
		if not proxies:
			return
		url = proxies.get("https") or proxies.get("http")
		with self._lock:
			for item in self._items:
				if item["url"] == url:
					item["fails"] += 1
					if item["fails"] >= max_fail:
						self._items.remove(item)
						print("[proxy] 剔除失效代理：%s" % url)
					break


class AnjukeAPI:
	"""安居客接口客户端。"""

	def __init__(
		self,
		device: Optional[DeviceProfile] = None,
		qps: float = 3.0,
		timeout: float = 20.0,
		retries: int = 2,
		verify: bool = True,
		proxy_pool: Optional[ProxyPool] = None,
	):
		self.device = device or DeviceProfile.load()
		self.timeout = timeout
		self.retries = max(0, int(retries))
		self.limiter = RateLimiter(qps)
		self.proxy_pool = proxy_pool or ProxyPool()
		self.session = requests.Session()
		self.session.headers["user-agent"] = UA
		self.verify = verify

	# ---------------- 公共参数 ----------------

	def _common(self, city_id: int) -> Dict[str, str]:
		d = self.device
		params = {
			"app": "a-ajk",
			"_guid": d.guid,
			"m2": d.model,
			"version_code": self.device.version_code,
			"m": self.device.model,
			"cv": self.device.app_version,
			"v": self.device.os_version,
			"manufacturer": self.device.manufacturer,
			"o": d.os_build,
			"qtime": time.strftime("%Y%m%d%H%M%S"),
			"ajk_city_id": str(city_id),
			"from": "mobile",
			"pm": "b66",
			"cid": "",
		}
		params.update(d.device_params())
		return params

	# ---------------- 底层请求 ----------------

	def _get(
		self,
		url: str,
		params: Dict[str, Any],
		headers: Dict[str, str],
		signed: bool = False,
		expect: str = "status0",
	) -> Dict[str, Any]:
		last_error: Optional[Exception] = None

		# 重试策略：401/403 换 nsign_uuid 重签；网络异常/非 JSON 指数退避；
		# 业务 status 错误说明参数有问题，直接抛出、不重试
		for attempt in range(self.retries + 1):
			self.limiter.wait()
			h = dict(headers)
			if signed:
				# 签名只吃 path，不能带域名
				sign_path = urllib.parse.urlsplit(url).path
				nsign, uid = make_nsign(sign_path, b"", params)
				h["nsign"] = nsign
				h["nsign_uuid"] = uid
			# 获取代理ip
			proxies = self.proxy_pool.get()
			try:
				resp = self.session.get(url, params=params, headers=h,
										timeout=self.timeout, proxies=proxies,
										verify=self.verify)
			except requests.RequestException as exc:
				last_error = exc
				self.proxy_pool.fail(proxies)
				if attempt < self.retries:
					time.sleep(0.5 * (2 ** attempt))
					continue
				raise ApiError("网络请求失败：%s" % exc) from exc

			if resp.status_code in (401, 403):
				last_error = ApiError("HTTP %d（签名/风控）" % resp.status_code,
									  resp.status_code)
				if proxies:
					self.proxy_pool.fail(proxies)
				if attempt < self.retries:
					time.sleep(0.4 * (attempt + 1))
					continue
				raise last_error

			if resp.status_code != 200:
				raise ApiError("HTTP %d：%s" % (resp.status_code, resp.text[:200]),
							   resp.status_code)

			try:
				payload = resp.json()
			except ValueError as exc:
				last_error = ApiError("响应不是 JSON：%s" % resp.text[:200],
									  resp.status_code)
				if attempt < self.retries:
					time.sleep(0.5 * (2 ** attempt))
					continue
				raise last_error from exc

			if self._ok(payload, expect):
				return payload

			raise ApiError(
				"业务失败 status=%r msg=%r" % (payload.get("status"), payload.get("msg")),
				200, payload)

		raise ApiError("请求失败：%s" % last_error)

	@staticmethod
	def _ok(payload: Dict[str, Any], expect: str) -> bool:
		if expect == "true":
			return payload.get("status") == "true"
		return payload.get("status") in (0, "0")

	# ---------------- 业务接口 ----------------

	def city_meta(self, city_id: int, abbr: str) -> Dict[str, Any]:
		"""接口1：城市区/商圈/地铁（无需签名）。"""
		params = self._common(city_id)
		params.update({
			"localName": abbr,
			"os": "android",
			"curVer": self.device.app_version,
			"areaVer": "",
			"appId": "1",
			"format": "json",
			"cityId": str(city_id),
			"subwayVer": "",
			"schoolVer": "",
		})
		# 元数据接口不参与签名，且必须用 apirent 域名的独立请求头（dirname/cid）
		return self._get(META_HOST + PATH_CITY_META, params,
						 self.device.apirent_headers(city_id, abbr),
						 signed=False, expect="status0")

	def area_filters(self, city_id: int) -> Dict[str, Any]:
		"""二手房区域树：区 typeid / 商圈 typeid。"""
		params = {"city_id": str(city_id)}
		params.update(self._common(city_id))
		# 这里的 regions[].typeid 才是列表接口认的 area_id（接口1 的区 id 不能用）
		return self._get(API_HOST + PATH_AREA_FILTER, params,
						 self.device.business_headers(), signed=True)

	def esf_page(
		self,
		city_id: int,
		page: int = 1,
		page_size: int = 25,
		keyword: str = "",
		area_id: Optional[int] = None,
		shangquan_id: Optional[int] = None,
		line_id: Optional[int] = None,
		station_id: Optional[int] = None,
		entry: str = "11",
	) -> Dict[str, Any]:
		"""二手房列表。

		四个维度参数最多传一个（区/商圈/地铁线/地铁站），全空表示全城；
		这些参数会参与 nsign 计算，所以必须与实际发送的 params 是同一份。
		"""
		params = {
			"show_recent_tips": "1",
			"is_ax_partition": "0",
			"q": keyword or "",
			"map_type": "google",
			"page_id": "SecondHouseSearchResultActivity_%d" % int(time.time() * 1000),
			"entry": entry,
			"with_broker_recommend": "0",
			"tab_type": "property",
			"is_struct": "1",
			"page": str(page),
			"page_size": str(page_size),
			"city_id": str(city_id),
		}
		if area_id is not None:
			params["area_id"] = str(area_id)
		if shangquan_id is not None:
			params["shangquan_id"] = str(shangquan_id)
		if line_id is not None:
			params["line_id"] = str(line_id)
		if station_id is not None:
			params["station_id"] = str(station_id)
		params.update(self._common(city_id))
		return self._get(API_HOST + PATH_ESF, params,
						 self.device.business_headers(), signed=True)

	def xf_page(
		self,
		city_id: int,
		page: int = 1,
		page_size: int = 20,
		keyword: str = "",
	) -> Dict[str, Any]:
		"""新房楼盘列表。

		page_size 必须是 20（传 25 会返回 status="false"）；
		关键词走 entry=xf_shouyesousuo_1 + keywords。
		"""
		params = {
			"map_type": "1",
			"entry": "xf_shouyesousuo_1" if keyword else "xf_shouye_1",
			"page": str(page),
			"page_size": str(page_size),
			"city_id": str(city_id),
		}
		if keyword:
			params["keywords"] = keyword
		params.update(self._common(city_id))
		return self._get(API_HOST + PATH_XF, params,
						 self.device.business_headers(), signed=True, expect="true")
