"""What the Telegram bot is allowed to know about the rest of the system.

The bot depends on the Protocols in `ports.py` and the dataclasses in
`read_models.py` - nothing else. It does not import subscription, payment, or
ticket aggregates, because those live in phases that are not built yet.

That constraint is the point: the entire bot was written and tested against
fakes before a single subscription table existed.
"""
