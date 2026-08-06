"""ASGI entrypoint for the bot (webhook receiver) container."""

from geekvpn.presentation.bot.app import create_bot_app

app = create_bot_app()
