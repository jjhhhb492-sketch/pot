import os
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

from db import db  # noqa: E402

logging.basicConfig(level=logging.INFO)

COGS = [
    "welcome", "info", "admin", "moderation", "tickets", "levels",
    "autoreply", "roles", "starboard", "logs", "tempvoice",
]


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._web = None

    async def setup_hook(self):
        db.init()
        for name in COGS:
            await self.load_extension(f"cogs.{name}")
        await self.tree.sync()
        await self.start_web()

    async def start_web(self):
        async def ok(_):
            return web.Response(text="Bot is alive ✅")

        app = web.Application()
        app.router.add_get("/", ok)
        app.router.add_get("/health", ok)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000)))
        await site.start()

    async def on_ready(self):
        await self.change_presence(activity=discord.Game("/help"))
        logging.info("Logged in as %s", self.user)


bot = Bot()


@bot.tree.error
async def on_app_error(i: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ ما عندك الصلاحيات المطلوبة."
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "❌ البوت ما عنده الصلاحيات الكافية."
    else:
        logging.exception("Command error", exc_info=error)
        msg = "❌ صار خطأ غير متوقع."
    try:
        if i.response.is_done():
            await i.followup.send(msg, ephemeral=True)
        else:
            await i.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
