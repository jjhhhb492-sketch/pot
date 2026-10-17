import discord
from discord import app_commands
from discord.ext import commands

from db import get_settings, set_setting, unset_setting
from utils import embed, OK, ERR, WARN


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    group = app_commands.Group(
        name="logs", description="سجلات السيرفر",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @group.command(name="set", description="تحديد روم السجلات")
    async def set_logs(self, i: discord.Interaction, channel: discord.TextChannel):
        await set_setting(i.guild_id, log_channel=channel.id)
        await i.response.send_message(f"✅ السجلات في {channel.mention}", ephemeral=True)

    @group.command(name="disable", description="إيقاف السجلات")
    async def disable(self, i: discord.Interaction):
        await unset_setting(i.guild_id, "log_channel")
        await i.response.send_message("✅ تم الإيقاف.", ephemeral=True)

    async def log(self, guild: discord.Guild, e: discord.Embed):
        s = await get_settings(guild.id)
        ch = guild.get_channel(s.get("log_channel") or 0)
        if ch:
            try:
                await ch.send(embed=e)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, m: discord.Message):
        if not m.guild or m.author.bot:
            return
        e = embed("🗑️ رسالة محذوفة", f"**الكاتب:** {m.author.mention}\n**الروم:** {m.channel.mention}\n\n{(m.content or '*بدون نص*')[:1000]}", ERR)
        await self.log(m.guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, b: discord.Message, a: discord.Message):
        if not b.guild or b.author.bot or b.content == a.content:
            return
        e = embed("✏️ رسالة معدّلة", f"**الكاتب:** {b.author.mention}\n**الروم:** {b.channel.mention} — [الذهاب]({a.jump_url})", WARN)
        e.add_field(name="قبل", value=(b.content or "—")[:1000], inline=False)
        e.add_field(name="بعد", value=(a.content or "—")[:1000], inline=False)
        await self.log(b.guild, e)

    @commands.Cog.listener()
    async def on_member_join(self, m: discord.Member):
        await self.log(m.guild, embed("📥 دخول", f"{m.mention}\nعمر الحساب: {discord.utils.format_dt(m.created_at, 'R')}", OK))

    @commands.Cog.listener()
    async def on_member_remove(self, m: discord.Member):
        await self.log(m.guild, embed("📤 خروج", f"{m} (`{m.id}`)", 0x95A5A6))

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.log(guild, embed("🔨 حظر", f"{user} (`{user.id}`)", ERR))

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.log(guild, embed("♻️ فك حظر", f"{user} (`{user.id}`)", OK))

    @commands.Cog.listener()
    async def on_member_update(self, b: discord.Member, a: discord.Member):
        if b.roles != a.roles:
            added = [r.mention for r in a.roles if r not in b.roles]
            removed = [r.mention for r in b.roles if r not in a.roles]
            text = f"{a.mention}\n"
            if added:
                text += f"➕ {' '.join(added)}\n"
            if removed:
                text += f"➖ {' '.join(removed)}"
            await self.log(a.guild, embed("🎭 تغيير رتب", text))
        elif b.nick != a.nick:
            await self.log(a.guild, embed("📝 تغيير لقب", f"{a.mention}\n`{b.nick}` ← `{a.nick}`"))

    @commands.Cog.listener()
    async def on_voice_state_update(self, m, b, a):
        if b.channel == a.channel:
            return
        if not b.channel:
            text = f"{m.mention} دخل 🔊 {a.channel.mention}"
        elif not a.channel:
            text = f"{m.mention} خرج من 🔊 {b.channel.mention}"
        else:
            text = f"{m.mention} انتقل من {b.channel.mention} إلى {a.channel.mention}"
        await self.log(m.guild, embed("🎙️ صوت", text))


async def setup(bot):
    await bot.add_cog(Logs(bot))
