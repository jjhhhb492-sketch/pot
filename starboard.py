import discord
from discord import app_commands
from discord.ext import commands

from db import db, get_settings, set_setting, unset_setting

STAR = "⭐"


class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    group = app_commands.Group(
        name="starboard", description="لوحة النجوم",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @group.command(name="setup", description="تفعيل لوحة النجوم")
    async def setup_sb(self, i: discord.Interaction, channel: discord.TextChannel,
                       threshold: app_commands.Range[int, 1, 50] = 3):
        await set_setting(i.guild_id, star_channel=channel.id, star_threshold=threshold)
        await i.response.send_message(f"✅ الرسائل اللي توصل {threshold} ⭐ تنزل في {channel.mention}", ephemeral=True)

    @group.command(name="disable", description="إيقاف لوحة النجوم")
    async def disable(self, i: discord.Interaction):
        await unset_setting(i.guild_id, "star_channel", "star_threshold")
        await i.response.send_message("✅ تم الإيقاف.", ephemeral=True)

    async def update(self, p: discord.RawReactionActionEvent):
        if str(p.emoji) != STAR or not p.guild_id:
            return
        s = await get_settings(p.guild_id)
        sc_id = s.get("star_channel")
        if not sc_id or p.channel_id == sc_id:
            return
        guild = self.bot.get_guild(p.guild_id)
        star_ch = guild.get_channel(sc_id) if guild else None
        channel = guild.get_channel(p.channel_id) if guild else None
        if not star_ch or not channel:
            return
        try:
            msg = await channel.fetch_message(p.message_id)
        except discord.HTTPException:
            return
        reaction = discord.utils.get(msg.reactions, emoji=STAR)
        count = 0
        if reaction:
            count = len([u async for u in reaction.users() if u.id != msg.author.id])

        _id = f"{p.guild_id}:{p.message_id}"
        doc = await db.stars.find_one({"_id": _id})
        content = f"{STAR} **{count}** | {channel.mention}"
        if doc:
            try:
                sm = await star_ch.fetch_message(doc["star_msg"])
                await sm.edit(content=content)
            except discord.HTTPException:
                pass
            return
        if count < s.get("star_threshold", 3):
            return
        e = discord.Embed(description=msg.content or None, color=0xFFAC33, timestamp=msg.created_at)
        e.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
        e.add_field(name="المصدر", value=f"[الانتقال للرسالة]({msg.jump_url})")
        if msg.attachments and (msg.attachments[0].content_type or "").startswith("image"):
            e.set_image(url=msg.attachments[0].url)
        sent = await star_ch.send(content, embed=e)
        await db.stars.insert_one({"_id": _id, "star_msg": sent.id})

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, p):
        await self.update(p)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, p):
        await self.update(p)


async def setup(bot):
    await bot.add_cog(Starboard(bot))
