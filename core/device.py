# -*- coding: utf-8 -*-
"""设备身份：生成一次、落盘复用，供所有请求共享。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import string
import time
import uuid as uuidlib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Dict, Optional

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "device.json"

_RAND = string.ascii_letters + string.digits


def _token(n: int = 6) -> str:
    return "".join(random.choice(_RAND) for _ in range(n))


@dataclass
class DeviceProfile:
    uuid: str          # <uuid4>-<6位>
    guid: str          # _guid
    identity: str      # identity
    openudid: str      # guest<uuid4>-<6位>
    gmid: str
    udid3: str         # <uuid4>-<13位毫秒>
    clientid_58: str
    xxzlxxid: str

    model: str = "Android-RMX2202"
    manufacturer: str = "realme"
    os_build: str = "qssi-user 14 UKQ1.230924.001 1741082883442 release-keys"
    os_version: str = "14"
    app_version: str = "17.43.1"
    version_code: str = "322406"
    memberid: str = "0"

    # ---------------- 生成 / 持久化 ----------------

    @classmethod
    def generate(cls) -> "DeviceProfile":
        openudid = "guest%s-%s" % (uuidlib.uuid4(), _token())
        return cls(
            uuid="%s-%s" % (uuidlib.uuid4(), _token()),
            guid=str(uuidlib.uuid4()),
            identity=str(uuidlib.uuid4()),
            openudid=openudid,
            gmid=openudid,
            udid3="%s-%d" % (uuidlib.uuid4(), int(time.time() * 1000)),
            clientid_58=hashlib.md5(os.urandom(16)).hexdigest(),
            xxzlxxid=base64.b64encode(os.urandom(48)).decode(),
        )

    @classmethod
    def from_dict(cls, data: Dict) -> "DeviceProfile":
        known = {f.name for f in fields(cls)}
        clean = {k: str(v) for k, v in data.items() if k in known and v is not None}
        return cls(**clean)

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH, refresh: bool = False) -> "DeviceProfile":
        path = Path(path)
        if not refresh and path.is_file():
            try:
                return cls.from_dict(json.loads(path.read_text("utf-8")))
            except Exception:
                pass
        device = cls.generate()
        try:
            device.save(path)
        except OSError as exc:
            print("[warn] 设备文件写入失败（%s），本次使用临时身份" % exc)
        return device

    def save(self, path: Path = DEFAULT_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, path)

    # ---------------- 映射到请求 ----------------

    def device_params(self) -> Dict[str, str]:
        return {
            "uuid": self.uuid,
            "_guid": self.guid,
            "identity": self.identity,
            "openudid": self.openudid,
            "gmid": self.gmid,
            "udid3": self.udid3,
            "58clientid": self.clientid_58,
        }

    def business_headers(self) -> Dict[str, str]:
        """业务域名（api.anjuke.com）的固定头。"""
        return {
            "accept": "image/webp,image/*,*/*;q=0.8",
            "memberid": self.memberid,
            "xxzlxxid": self.xxzlxxid,
            "user-agent": "a-ajk/%s/%s/android/%s" % (
                self.app_version, self.model, self.os_version),
            "guestimei": self.openudid,
            "58clientid": self.clientid_58,
            "switchrecommend": "",
            "openudid": self.openudid,
        }

    def apirent_headers(self, city_id: int, abbr: str) -> Dict[str, str]:
        """城市元数据域名（apirent.anjuke.com）的独立头。"""
        return {
            "Host": "apirent.anjuke.com",
            "dirname": abbr,
            "platform": "android",
            "productorid": "47",
            "osarch": "arm64-v8a",
            "bundle": "com.anjuke.android.app",
            "os": "android",
            "cid": str(city_id),
            "accept": "image/webp,image/*,*/*;q=0.8",
            "securityversion": "0.1.0",
            "user-agent": "okhttp/4.9.2",
        }


def load_device(path: Optional[Path] = None, refresh: bool = False) -> DeviceProfile:
    return DeviceProfile.load(Path(path) if path else DEFAULT_PATH, refresh=refresh)
