"""``Notifier`` adapters (ADR-0040).

Available now: ``DiscordWebhookNotifier``, which posts each alert to one Discord
channel through its webhook, with the standard library's ``urllib``.

Later: a Discord bot with ``/status``, ``/kill`` and ``/resume`` (brief §9).
"""

from tyche.adapters.notifiers.discord import (
    MAX_CONTENT,
    DiscordWebhookNotifier,
    HttpResponse,
    Transport,
    content,
    payload,
    urllib_post,
)

__all__ = [
    "MAX_CONTENT",
    "DiscordWebhookNotifier",
    "HttpResponse",
    "Transport",
    "content",
    "payload",
    "urllib_post",
]
