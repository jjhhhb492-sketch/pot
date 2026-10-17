import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import embed, OK


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="say", description="البوت يكتب رسالة في أي روم (مثلاً الشات العام)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def say(self, i: discord.Interaction, message: str, channel: discord.TextChannel | None = None):
        ch = channel or i.channel
        await ch.send(message.replace("\\n", "\n"))
        await i.response.send_message(f"✅ تم الإرسال في {ch.mention}", ephemeral=True)

    @app_commands.command(name="announce", description="إعلان بشكل Embed احترافي")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.choices(ping=[
        app_commands.Choice(name="بدون منشن", value="none"),
        app_commands.Choice(name="@everyone", value="everyone"),
        app_commands.Choice(name="@here", value="here"),
    ])
    async def announce(self, i: discord.Interaction, channel: discord.TextChannel, title: str, message: str,
                       ping: app_commands.Choice[str] | None = None, image_url: str | None = None):
        e = embed(f"📢 {title}", message.replace("\\n", "\n"))
        e.set_footer(text=i.guild.name, icon_url=i.guild.icon.url if i.guild.icon else None)
        if image_url:
            e.set_image(url=image_url)
        content = {"everyone": "@everyone", "here": "@here"}.get(ping.value if ping else "none")
        await channel.send(content=content, embed=e, allowed_mentions=discord.AllowedMentions(everyone=True))
        await i.response.send_message(f"✅ تم النشر في {channel.mention}", ephemeral=True)

    @app_commands.command(name="dm", description="إرسال رسالة خاصة لعضو")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def dm(self, i: discord.Interaction, member: discord.Member, message: str):
        try:
            await member.send(embed=embed(f"📩 رسالة من {i.guild.name}", message.replace("\\n", "\n")))
            await i.response.send_message("✅ تم الإرسال.", ephemeral=True)
        except discord.HTTPException:
            await i.response.send_message("❌ الخاص مقفول عند العضو.", ephemeral=True)

    @app_commands.command(name="dmrole", description="رسالة خاصة لكل أعضاء رتبة معينة (بطيء عمداً لتفادي الحظر)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def dmrole(self, i: discord.Interaction, role: discord.Role, message: str):
        await i.response.defer(ephemeral=True)
        targets = [m for m in role.members if not m.bot]
        sent = failed = 0
        for m in targets:
            try:
                await m.send(embed=embed(f"📩 رسالة من {i.guild.name}", message.replace("\\n", "\n")))
                sent += 1
            except discord.HTTPException:
                failed += 1
            await asyncio.sleep(2)
        await i.followup.send(embed=embed("✅ انتهى", f"وصلت: **{sent}**\nفشلت: **{failed}**", OK), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
