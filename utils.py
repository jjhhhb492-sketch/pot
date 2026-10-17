import discord

COLOR = 0x5865F2
OK = 0x2ECC71
ERR = 0xE74C3C
WARN = 0xF1C40F


def embed(title=None, desc=None, color=COLOR, **kw) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color, **kw)


def fmt(text: str, member: discord.Member) -> str:
    return (
        text.replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


def bar(value: int, total: int, size: int = 10) -> str:
    n = int(size * value / total) if total else 0
    return "█" * n + "░" * (size - n)


# ---------- الصور (ترحيب / تذاكر) ----------
import io
import os
from db import db, set_setting, unset_setting

MAX_IMG = 5 * 1024 * 1024


async def set_image(gid: int, key: str, attachment: discord.Attachment | None, url: str | None) -> str | None:
    """يحفظ صورة مرفوعة (تتخزن في القاعدة) أو رابط. يرجع نص خطأ أو None."""
    if attachment:
        if not (attachment.content_type or "").startswith("image/"):
            return "❌ الملف لازم يكون صورة."
        if attachment.size > MAX_IMG:
            return "❌ الصورة أكبر من 5MB."
        data = await attachment.read()
        ext = os.path.splitext(attachment.filename)[1].lower() or ".png"
        await db.images.update_one({"_id": f"{gid}:{key}"},
                                   {"$set": {"data": data, "name": f"{key}{ext}"}}, upsert=True)
        await unset_setting(gid, f"{key}_url")
    elif url:
        if not url.startswith(("http://", "https://")):
            return "❌ الرابط غير صحيح."
        await db.images.delete_one({"_id": f"{gid}:{key}"})
        await set_setting(gid, **{f"{key}_url": url})
    return None


async def apply_image(gid: int, key: str, e: discord.Embed, settings: dict) -> discord.File | None:
    """يضيف الصورة للـ embed، ويرجع File لو الصورة مخزنة (لازم ترسل معها)."""
    doc = await db.images.find_one({"_id": f"{gid}:{key}"})
    if doc:
        e.set_image(url=f"attachment://{doc['name']}")
        return discord.File(io.BytesIO(doc["data"]), filename=doc["name"])
    if url := settings.get(f"{key}_url"):
        e.set_image(url=url)
    return None
