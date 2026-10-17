import random
import time
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from pymongo import ReturnDocument

from db import db, get_settings, set_setting, unset_setting
from utils import embed, bar, OK


def xp_needed(level: int) -> int:
    return 5 * level ** 2 + 50 * level + 100


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cd: dict = {}

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild:
            return
        key = (m.guild.id, m.author.id)
        now = time.time()
        if now - self.cd.get(key, 0) < 60:
            return
        self.cd[key] = now
        _id = f"{m.guild.id}:{m.author.id}"
        doc = await db.levels.find_one_and_update(
            {"_id": _id},
            {"$inc": {"xp": random.randint(15, 25)}, "$setOnInsert": {"gid": m.guild.id, "uid": m.author.id, "level": 0}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        lvl, xp = doc["level"], doc["xp"]
        need = xp_needed(lvl)
        if xp < need:
            return
        lvl += 1
        await db.levels.update_one({"_id": _id}, {"$set": {"xp": xp - need, "level": lvl}})
        try:
            await m.channel.send(f"🎉 مبروك {m.author.mention}! وصلت **المستوى {lvl}**")
        except discord.HTTPException:
            pass
        s = await get_settings(m.guild.id)
        rid = s.get("level_roles", {}).get(str(lvl))
        if rid and (role := m.guild.get_role(rid)):
            try:
                await m.author.add_roles(role, reason=f"Level {lvl}")
            except discord.HTTPException:
                pass

    @app_commands.command(name="rank", description="مستواك وخبرتك")
    @app_commands.guild_only()
    async def rank(self, i: discord.Interaction, member: discord.Member | None = None):
        m = member or i.user
        doc = await db.levels.find_one({"_id": f"{i.guild_id}:{m.id}"}) or {"level": 0, "xp": 0}
        lvl, xp = doc["level"], doc["xp"]
        pos = 1 + await db.levels.count_documents({"gid": i.guild_id, "$or": [
            {"level": {"$gt": lvl}}, {"level": lvl, "xp": {"$gt": xp}}]})
        need = xp_needed(lvl)
        e = embed(f"📊 {m.display_name}", f"**المركز:** #{pos}\n**المستوى:** {lvl}\n{bar(xp, need)} `{xp}/{need}`")
        e.set_thumbnail(url=m.display_avatar.url)
        await i.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="أفضل 10 أعضاء")
    @app_commands.guild_only()
    async def leaderboard(self, i: discord.Interaction):
        docs = await db.levels.find({"gid": i.guild_id}).sort([("level", -1), ("xp", -1)]).to_list(10)
        if not docs:
            return await i.response.send_message("ما في بيانات للحين.", ephemeral=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[n] if n < 3 else f'`{n + 1}`'} <@{d['uid']}> — المستوى **{d['level']}**" for n, d in enumerate(docs)]
        await i.response.send_message(embed=embed("🏆 لوحة الصدارة", "\n".join(lines)))

    @app_commands.command(name="daily", description="مكافأتك اليومية")
    @app_commands.guild_only()
    async def daily(self, i: discord.Interaction):
        _id = f"{i.guild_id}:{i.user.id}"
        doc = await db.economy.find_one({"_id": _id}) or {}
        now = datetime.now(timezone.utc)
        last = doc.get("last_daily")
        if last and now - last < timedelta(hours=24):
            return await i.response.send_message(
                f"⏳ تقدر تستلم {discord.utils.format_dt(last + timedelta(hours=24), 'R')}", ephemeral=True)
        streak = doc.get("streak", 0) + 1 if last and now - last < timedelta(hours=48) else 1
        reward = 100 + min(streak, 7) * 25
        await db.economy.update_one(
            {"_id": _id},
            {"$inc": {"coins": reward}, "$set": {"last_daily": now, "streak": streak, "gid": i.guild_id, "uid": i.user.id}},
            upsert=True)
        await i.response.send_message(embed=embed("🎁 المكافأة اليومية", f"استلمت **{reward}** 💰\n🔥 السلسلة: **{streak}** يوم", OK))

    @app_commands.command(name="balance", description="رصيدك")
    @app_commands.guild_only()
    async def balance(self, i: discord.Interaction, member: discord.Member | None = None):
        m = member or i.user
        doc = await db.economy.find_one({"_id": f"{i.guild_id}:{m.id}"}) or {}
        await i.response.send_message(embed=embed(f"💰 رصيد {m.display_name}", f"**{doc.get('coins', 0)}** عملة"))

    levelrole = app_commands.Group(
        name="levelrole", description="رتب المستويات",
        default_permissions=discord.Permissions(manage_roles=True), guild_only=True,
    )

    @levelrole.command(name="add", description="رتبة تعطى عند الوصول لمستوى")
    async def lr_add(self, i: discord.Interaction, level: app_commands.Range[int, 1, 500], role: discord.Role):
        await set_setting(i.guild_id, **{f"level_roles.{level}": role.id})
        await i.response.send_message(f"✅ المستوى {level} ← {role.mention}", ephemeral=True)

    @levelrole.command(name="remove", description="حذف رتبة مستوى")
    async def lr_remove(self, i: discord.Interaction, level: app_commands.Range[int, 1, 500]):
        await unset_setting(i.guild_id, f"level_roles.{level}")
        await i.response.send_message("✅ تم الحذف.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Levels(bot))
