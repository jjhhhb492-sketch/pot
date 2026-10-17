import os
import time
from motor.motor_asyncio import AsyncIOMotorClient


class _DB:
    """غلاف كسول: الاتصال يتم داخل حلقة asyncio بعد تشغيل البوت."""
    _db = None

    def init(self):
        client = AsyncIOMotorClient(os.environ["MONGO_URI"], tz_aware=True)
        self._db = client[os.getenv("DB_NAME", "discord_bot")]

    def __getattr__(self, name):
        return getattr(self._db, name)


db = _DB()

_cache: dict = {}
_TTL = 30


async def get_settings(gid: int) -> dict:
    hit = _cache.get(gid)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    doc = await db.settings.find_one({"_id": gid}) or {}
    _cache[gid] = (time.time(), doc)
    return doc


async def set_setting(gid: int, **kw):
    await db.settings.update_one({"_id": gid}, {"$set": kw}, upsert=True)
    _cache.pop(gid, None)


async def unset_setting(gid: int, *keys):
    await db.settings.update_one({"_id": gid}, {"$unset": {k: "" for k in keys}})
    _cache.pop(gid, None)


async def list_add(gid: int, key: str, value):
    await db.settings.update_one({"_id": gid}, {"$addToSet": {key: value}}, upsert=True)
    _cache.pop(gid, None)


async def list_remove(gid: int, key: str, value):
    await db.settings.update_one({"_id": gid}, {"$pull": {key: value}})
    _cache.pop(gid, None)
