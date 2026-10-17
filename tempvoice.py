import discord
from discord import app_commands
from discord.ext import commands

from db import db, get_settings, set_setting, unset_setting


class TempVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    group = app_commands.Group(
        name="tempvoice", description="رومات صوتية مؤقتة",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @group.command(name="setup", description="اختر روم 'انضم لإنشاء روم'")
    async def setup_tv(self, i: discord.Interaction, channel: discord.VoiceChannel):
        await set_setting(i.guild_id, tempvoice_channel=channel.id)
        await i.response.send_message(f"✅ أي عضو يدخل {channel.mention} ينشأ له روم خاص.", ephemeral=True)

    @group.command(name="disable", description="إيقاف الرومات المؤقتة")
    async def disable(self, i: discord.Interaction):
        await unset_setting(i.guild_id, "tempvoice_channel")
        await i.response.send_message("✅ تم الإيقاف.", ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, m: discord.Member, b: discord.VoiceState, a: discord.VoiceState):
        s = await get_settings(m.guild.id)
        if a.channel and a.channel.id == s.get("tempvoice_channel"):
            try:
                ch = await m.guild.create_voice_channel(
                    f"🔊 {m.display_name}", category=a.channel.category,
                    overwrites={m: discord.PermissionOverwrite(manage_channels=True, move_members=True)},
                    reason="Temp voice")
                await db.tempvoice.insert_one({"_id": ch.id})
                await m.move_to(ch)
            except discord.HTTPException:
                pass
        if b.channel and b.channel != a.channel and not b.channel.members:
            if await db.tempvoice.find_one({"_id": b.channel.id}):
                try:
                    await b.channel.delete(reason="Temp voice empty")
                except discord.HTTPException:
                    pass
                await db.tempvoice.delete_one({"_id": b.channel.id})


async def setup(bot):
    await bot.add_cog(TempVoice(bot))
