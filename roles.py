import discord
from discord import app_commands
from discord.ext import commands

from utils import embed


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"rp:(?P<id>[0-9]+)"):
    def __init__(self, role_id: int, label: str = "رتبة"):
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"rp:{role_id}"))
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["id"]), item.label or "رتبة")

    async def callback(self, i: discord.Interaction):
        role = i.guild.get_role(self.role_id)
        if not role:
            return await i.response.send_message("❌ الرتبة غير موجودة.", ephemeral=True)
        try:
            if role in i.user.roles:
                await i.user.remove_roles(role)
                msg = f"➖ تم سحب {role.mention}"
            else:
                await i.user.add_roles(role)
                msg = f"➕ تم إعطاؤك {role.mention}"
        except discord.Forbidden:
            msg = "❌ رتبة البوت لازم تكون أعلى من هذي الرتبة."
        await i.response.send_message(msg, ephemeral=True)


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(RoleButton)

    @app_commands.command(name="rolepanel", description="لوحة رتب بالأزرار (حتى 5 رتب)")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rolepanel(self, i: discord.Interaction, title: str, role1: discord.Role,
                        role2: discord.Role | None = None, role3: discord.Role | None = None,
                        role4: discord.Role | None = None, role5: discord.Role | None = None,
                        description: str = "اضغط على الزر للحصول على الرتبة أو سحبها."):
        roles = [r for r in (role1, role2, role3, role4, role5) if r]
        view = discord.ui.View(timeout=None)
        for r in roles:
            view.add_item(RoleButton(r.id, r.name))
        await i.channel.send(embed=embed(title, description), view=view)
        await i.response.send_message("✅ تم إنشاء اللوحة.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Roles(bot))
