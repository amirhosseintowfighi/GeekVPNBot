"""ASGI entrypoint for the API container."""

from geekvpn.presentation.api.app import create_app

app = create_app()
