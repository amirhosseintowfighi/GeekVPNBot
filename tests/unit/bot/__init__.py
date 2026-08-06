"""Telegram bot unit tests.

The modules that touch aiogram are guarded with `importorskip`, so this
package still gives useful signal in an environment where aiogram is not
installed - which covers the pure formatting, read-model, and pricing-ladder
logic, i.e. most of the places a bug would actually hide.
"""
