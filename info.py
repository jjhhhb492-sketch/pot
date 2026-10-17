import discord
from discord import app_commands
from discord.ext import commands

from db import db
from utils import embed, bar


class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="سرعة البوت")
    async def ping(self, i: discord.Interaction):
        await i.response.send_message(f"🏓 `{round(self.bot.latency * 1000)}ms`")

    @app_commands.command(name="avatar", description="صورة عضو")
    async def avatar(self, i: discord.Interaction, member: discord.Member | None = None):
        m = member or i.user
        e = embed(f"صورة {m.display_name}")
        e.set_image(url=m.display_avatar.url)
        await i.response.send_message(embed=e)

    @app_commands.command(name="user", description="معلومات عضو")
    @app_commands.guild_only()
    async def user(self, i: discord.Interaction, member: discord.Member | None = None):
        m = member or i.user
        roles = [r.mention for r in reversed(m.roles) if r != i.guild.default_role][:10]
        e = embed(str(m), color=m.color.value or 0x5865F2)
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="🆔 الآيدي", value=m.id)
        e.add_field(name="📅 أنشأ حسابه", value=discord.utils.format_dt(m.created_at, "R"))
        e.add_field(name="📥 دخل السيرفر", value=discord.utils.format_dt(m.joined_at, "R") if m.joined_at else "؟")
        e.add_field(name="🎭 الرتب", value=" ".join(roles) or "لا يوجد", inline=False)
        await i.response.send_message(embed=e)

    @app_commands.command(name="server", description="معلومات السيرفر")
    @app_commands.guild_only()
    async def server(self, i: discord.Interaction):
        g = i.guild
        e = embed(g.name)
        if g.icon:
            e.set_thumbnail(url=g.icon.url)
        e.add_field(name="👑 المالك", value=f"<@{g.owner_id}>")
        e.add_field(name="👥 الأعضاء", value=g.member_count)
        e.add_field(name="💬 الرومات", value=len(g.channels))
        e.add_field(name="🎭 الرتب", value=len(g.roles))
        e.add_field(name="🚀 البوستات", value=g.premium_subscription_count)
        e.add_field(name="📅 تاريخ الإنشاء", value=discord.utils.format_dt(g.created_at, "D"))
        await i.response.send_message(embed=e)

    @app_commands.command(name="profile", description="بروفايل كامل: مستوى + عملات")
    @app_commands.guild_only()
    async def profile(self, i: discord.Interaction, member: discord.Member | None = None):
        m = member or i.user
        key = f"{i.guild_id}:{m.id}"
        lv = await db.levels.find_one({"_id": key}) or {"level": 0, "xp": 0}
        eco = await db.economy.find_one({"_id": key}) or {"coins": 0, "streak": 0}
        need = 5 * lv["level"] ** 2 + 50 * lv["level"] + 100
        warns = await db.warns.count_documents({"gid": i.guild_id, "uid": m.id})
        e = embed(f"بروفايل {m.display_name}")
        e.set_thumbnail(url=m.display_avatar.url)
        e.add_field(name="⭐ المستوى", value=lv["level"])
        e.add_field(name="💰 العملات", value=eco["coins"])
        e.add_field(name="🔥 سلسلة اليومي", value=eco.get("streak", 0))
        e.add_field(name="📊 الخبرة", value=f"{bar(lv['xp'], need)} {lv['xp']}/{need}", inline=False)
        e.add_field(name="⚠️ التحذيرات", value=warns)
        e.add_field(name="📥 دخل", value=discord.utils.format_dt(m.joined_at, "R") if m.joined_at else "؟")
        await i.response.send_message(embed=e)

    @app_commands.command(name="help", description="قائمة الأوامر")
    async def help(self, i: discord.Interaction):
        e = embed("📖 قائمة الأوامر")
        e.add_field(name="ℹ️ معلومات", value="`/user` `/avatar` `/server` `/profile` `/ping`", inline=False)
        e.add_field(name="⭐ المستويات", value="`/rank` `/leaderboard` `/daily` `/balance`", inline=False)
        e.add_field(name="🛡️ الإدارة", value="`/ban` `/kick` `/timeout` `/untimeout` `/unban` `/warn` `/warnings` `/clearwarns` `/clear` `/lock` `/unlock` `/slowmode` `/automod`", inline=False)
        e.add_field(name="🎫 التذاكر", value="`/ticket setup`", inline=False)
        e.add_field(name="⚙️ الإعدادات", value="`/setup` `/logs` `/starboard` `/tempvoice` `/autoreply` `/rolepanel` `/levelrole`", inline=False)
        e.add_field(name="📢 الإدارة العامة", value="`/say` `/announce` `/dm` `/dmrole`", inline=False)
        await i.response.send_message(embed=e)


async def setup(bot):
    await bot.add_cog(Info(bot))
