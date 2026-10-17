import discord
from discord import app_commands
from discord.ext import commands

from db import db


class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache: dict[int, list] = {}

    async def load(self, gid: int) -> list:
        if gid not in self.cache:
            self.cache[gid] = await db.autoreplies.find({"gid": gid}).to_list(200)
        return self.cache[gid]

    group = app_commands.Group(
        name="autoreply", description="ردود تلقائية",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @group.command(name="add", description="إضافة رد تلقائي")
    async def add(self, i: discord.Interaction, trigger: str, response: str):
        await db.autoreplies.update_one({"gid": i.guild_id, "t": trigger.lower()},
                                        {"$set": {"r": response}}, upsert=True)
        self.cache.pop(i.guild_id, None)
        await i.response.send_message("✅ تمت الإضافة.", ephemeral=True)

    @group.command(name="remove", description="حذف رد تلقائي")
    async def remove(self, i: discord.Interaction, trigger: str):
        await db.autoreplies.delete_one({"gid": i.guild_id, "t": trigger.lower()})
        self.cache.pop(i.guild_id, None)
        await i.response.send_message("✅ تم الحذف.", ephemeral=True)

    @group.command(name="list", description="عرض الردود")
    async def list(self, i: discord.Interaction):
        items = await self.load(i.guild_id)
        text = "\n".join(f"• `{d['t']}` ← {d['r'][:60]}" for d in items) or "لا يوجد"
        await i.response.send_message(text, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, m: discord.Message):
        if m.author.bot or not m.guild or not m.content:
            return
        text = m.content.lower()
        for d in await self.load(m.guild.id):
            if d["t"] in text:
                try:
                    await m.reply(d["r"], mention_author=False)
                except discord.HTTPException:
                    pass
                break


async def setup(bot):
    await bot.add_cog(AutoReply(bot))
