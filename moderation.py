import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from db import db, get_settings, set_setting, list_add, list_remove
from utils import embed, OK, ERR, WARN

LINK = re.compile(r"(https?://|www\.|discord\.gg/|discord\.com/invite/)\S+", re.I)


def hierarchy_ok(i: discord.Interaction, target: discord.Member) -> bool:
    g = i.guild
    if target.id == g.owner_id or target.top_role >= g.me.top_role:
        return False
    if i.user.id == g.owner_id:
        return True
    return target.top_role < i.user.top_role


DENY = "❌ ما تقدر تتعامل مع هذا العضو (رتبته أعلى منك أو من البوت)."


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="kick", description="طرد عضو")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, i: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
        if not hierarchy_ok(i, member):
            return await i.response.send_message(DENY, ephemeral=True)
        await member.kick(reason=f"{i.user}: {reason}")
        await i.response.send_message(embed=embed("👢 تم الطرد", f"{member.mention}\nالسبب: {reason}", WARN))

    @app_commands.command(name="ban", description="حظر عضو")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, i: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
        if not hierarchy_ok(i, member):
            return await i.response.send_message(DENY, ephemeral=True)
        await member.ban(reason=f"{i.user}: {reason}")
        await i.response.send_message(embed=embed("🔨 تم الحظر", f"{member.mention}\nالسبب: {reason}", ERR))

    @app_commands.command(name="unban", description="فك حظر بالآيدي")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, i: discord.Interaction, user_id: str):
        try:
            await i.guild.unban(discord.Object(int(user_id)))
            await i.response.send_message(embed=embed("✅ تم فك الحظر", f"<@{user_id}>", OK))
        except (ValueError, discord.NotFound):
            await i.response.send_message("❌ آيدي غير صحيح أو غير محظور.", ephemeral=True)

    @app_commands.command(name="timeout", description="كتم مؤقت لعضو")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def timeout(self, i: discord.Interaction, member: discord.Member,
                      minutes: app_commands.Range[int, 1, 40320], reason: str = "بدون سبب"):
        if not hierarchy_ok(i, member):
            return await i.response.send_message(DENY, ephemeral=True)
        await member.timeout(timedelta(minutes=minutes), reason=f"{i.user}: {reason}")
        await i.response.send_message(embed=embed("🔇 تم الكتم", f"{member.mention} لمدة **{minutes}** دقيقة\nالسبب: {reason}", WARN))

    @app_commands.command(name="untimeout", description="فك الكتم")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def untimeout(self, i: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await i.response.send_message(embed=embed("🔊 تم فك الكتم", member.mention, OK))

    @app_commands.command(name="warn", description="تحذير عضو")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, i: discord.Interaction, member: discord.Member, reason: str):
        await db.warns.insert_one({"gid": i.guild_id, "uid": member.id, "mod": i.user.id,
                                   "reason": reason, "ts": datetime.now(timezone.utc)})
        count = await db.warns.count_documents({"gid": i.guild_id, "uid": member.id})
        try:
            await member.send(embed=embed(f"⚠️ تحذير في {i.guild.name}", f"السبب: {reason}\nعدد تحذيراتك: **{count}**", WARN))
        except discord.HTTPException:
            pass
        await i.response.send_message(embed=embed("⚠️ تم التحذير", f"{member.mention}\nالسبب: {reason}\nإجمالي التحذيرات: **{count}**", WARN))

    @app_commands.command(name="warnings", description="عرض تحذيرات عضو")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warnings(self, i: discord.Interaction, member: discord.Member):
        docs = await db.warns.find({"gid": i.guild_id, "uid": member.id}).sort("ts", -1).to_list(10)
        if not docs:
            return await i.response.send_message("✅ ما عنده تحذيرات.", ephemeral=True)
        lines = [f"• {discord.utils.format_dt(d['ts'], 'd')} — {d['reason']} (بواسطة <@{d['mod']}>)" for d in docs]
        await i.response.send_message(embed=embed(f"⚠️ تحذيرات {member.display_name}", "\n".join(lines), WARN), ephemeral=True)

    @app_commands.command(name="clearwarns", description="مسح تحذيرات عضو")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def clearwarns(self, i: discord.Interaction, member: discord.Member):
        r = await db.warns.delete_many({"gid": i.guild_id, "uid": member.id})
        await i.response.send_message(f"✅ تم مسح {r.deleted_count} تحذير.", ephemeral=True)

    @app_commands.command(name="clear", description="مسح رسائل")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def clear(self, i: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await i.response.defer(ephemeral=True)
        deleted = await i.channel.purge(limit=amount)
        await i.followup.send(f"🧹 تم مسح {len(deleted)} رسالة.", ephemeral=True)

    @app_commands.command(name="lock", description="قفل الروم")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, i: discord.Interaction):
        ow = i.channel.overwrites_for(i.guild.default_role)
        ow.send_messages = False
        await i.channel.set_permissions(i.guild.default_role, overwrite=ow)
        await i.response.send_message("🔒 تم قفل الروم.")

    @app_commands.command(name="unlock", description="فتح الروم")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, i: discord.Interaction):
        ow = i.channel.overwrites_for(i.guild.default_role)
        ow.send_messages = None
        await i.channel.set_permissions(i.guild.default_role, overwrite=ow)
        await i.response.send_message("🔓 تم فتح الروم.")

    @app_commands.command(name="slowmode", description="الوضع البطيء (0 للإيقاف)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def slowmode(self, i: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await i.channel.edit(slowmode_delay=seconds)
        await i.response.send_message(f"🐢 الوضع البطيء: **{seconds}** ثانية.")

    automod = app_commands.Group(
        name="automod", description="الحماية التلقائية",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @automod.command(name="antilink", description="منع الروابط")
    async def antilink(self, i: discord.Interaction, enabled: bool):
        await set_setting(i.guild_id, antilink=enabled)
        await i.response.send_message(f"🔗 منع الروابط: **{'مفعّل' if enabled else 'متوقف'}**", ephemeral=True)

    @automod.command(name="addword", description="إضافة كلمة ممنوعة")
    async def addword(self, i: discord.Interaction, word: str):
        await list_add(i.guild_id, "badwords", word.lower())
        await i.response.send_message("✅ تمت الإضافة.", ephemeral=True)

    @automod.command(name="removeword", description="حذف كلمة ممنوعة")
    async def removeword(self, i: discord.Interaction, word: str):
        await list_remove(i.guild_id, "badwords", word.lower())
        await i.response.send_message("✅ تم الحذف.", ephemeral=True)

    @automod.command(name="words", description="عرض الكلمات الممنوعة")
    async def words(self, i: discord.Interaction):
        s = await get_settings(i.guild_id)
        await i.response.send_message(", ".join(s.get("badwords", [])) or "لا يوجد", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or m.webhook_id:
            return
        if isinstance(m.author, discord.Member) and m.author.guild_permissions.manage_messages:
            return
        s = await get_settings(m.guild.id)
        text = m.content.lower()
        reason = None
        if s.get("antilink") and LINK.search(m.content):
            reason = "الروابط ممنوعة هنا"
        elif any(w in text for w in s.get("badwords", [])):
            reason = "كلمة ممنوعة"
        if reason:
            try:
                await m.delete()
                await m.channel.send(f"{m.author.mention} ⚠️ {reason}.", delete_after=5)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Moderation(bot))
