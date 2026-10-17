import discord
from discord import app_commands
from discord.ext import commands

from db import get_settings, set_setting, unset_setting
from utils import embed, fmt, OK, set_image, apply_image

DEFAULT_WELCOME = "أهلاً {user} في **{server}** 🎉\nأنت العضو رقم **{count}**"
DEFAULT_BYE = "**{username}** غادر السيرفر 👋"


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    setup = app_commands.Group(
        name="setup",
        description="إعدادات الترحيب والرتب التلقائية",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    @setup.command(name="welcome", description="تحديد روم الترحيب (رسالة وصورة اختيارية)")
    @app_commands.describe(message="المتغيرات: {user} {username} {server} {count}",
                           image="ارفع صورة بانر للترحيب", image_url="أو رابط صورة مباشر")
    async def welcome(self, i: discord.Interaction, channel: discord.TextChannel, message: str | None = None,
                      image: discord.Attachment | None = None, image_url: str | None = None):
        await i.response.defer(ephemeral=True)
        if err := await set_image(i.guild_id, "welcome", image, image_url):
            return await i.followup.send(err, ephemeral=True)
        data = {"welcome_channel": channel.id}
        if message:
            data["welcome_msg"] = message
        await set_setting(i.guild_id, **data)
        await i.followup.send(embed=embed("✅ تم", f"روم الترحيب: {channel.mention}", OK), ephemeral=True)

    @setup.command(name="goodbye", description="تحديد روم المغادرة (ورسالة اختيارية)")
    async def goodbye(self, i: discord.Interaction, channel: discord.TextChannel, message: str | None = None):
        data = {"goodbye_channel": channel.id}
        if message:
            data["goodbye_msg"] = message
        await set_setting(i.guild_id, **data)
        await i.response.send_message(embed=embed("✅ تم", f"روم المغادرة: {channel.mention}", OK), ephemeral=True)

    @setup.command(name="autorole", description="رتبة تعطى تلقائياً للأعضاء الجدد")
    async def autorole(self, i: discord.Interaction, role: discord.Role):
        await set_setting(i.guild_id, autorole=role.id)
        await i.response.send_message(embed=embed("✅ تم", f"الرتبة التلقائية: {role.mention}", OK), ephemeral=True)

    @setup.command(name="welcome-dm", description="رسالة خاصة للعضو الجديد (اتركها فارغة للإيقاف)")
    async def welcome_dm(self, i: discord.Interaction, message: str | None = None):
        if message:
            await set_setting(i.guild_id, welcome_dm=True, welcome_dm_msg=message)
            text = "✅ تم تفعيل رسالة الخاص."
        else:
            await unset_setting(i.guild_id, "welcome_dm", "welcome_dm_msg")
            text = "✅ تم إيقاف رسالة الخاص."
        await i.response.send_message(text, ephemeral=True)

    @setup.command(name="disable", description="إيقاف الترحيب والمغادرة والرتبة التلقائية")
    async def disable(self, i: discord.Interaction):
        await unset_setting(i.guild_id, "welcome_channel", "goodbye_channel", "autorole", "welcome_dm")
        await i.response.send_message("✅ تم الإيقاف.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, m: discord.Member):
        s = await get_settings(m.guild.id)
        if rid := s.get("autorole"):
            role = m.guild.get_role(rid)
            if role:
                try:
                    await m.add_roles(role, reason="Auto role")
                except discord.HTTPException:
                    pass
        if cid := s.get("welcome_channel"):
            ch = m.guild.get_channel(cid)
            if ch:
                e = embed("👋 عضو جديد", fmt(s.get("welcome_msg", DEFAULT_WELCOME), m))
                e.set_thumbnail(url=m.display_avatar.url)
                file = await apply_image(m.guild.id, "welcome", e, s)
                try:
                    await ch.send(m.mention, embed=e, file=file)
                except discord.HTTPException:
                    pass
        if s.get("welcome_dm"):
            try:
                await m.send(embed=embed(f"أهلاً في {m.guild.name}", fmt(s.get("welcome_dm_msg", DEFAULT_WELCOME), m)))
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, m: discord.Member):
        s = await get_settings(m.guild.id)
        if cid := s.get("goodbye_channel"):
            ch = m.guild.get_channel(cid)
            if ch:
                e = embed("👋 وداعاً", fmt(s.get("goodbye_msg", DEFAULT_BYE), m), 0x95A5A6)
                e.set_thumbnail(url=m.display_avatar.url)
                try:
                    await ch.send(embed=e)
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(Welcome(bot))
