"""Single-channel notification dispatch helpers."""

import logging
from typing import List, Optional, Protocol

logger = logging.getLogger(__name__)


class NotificationDispatchAdapter(Protocol):
    """Methods needed to dispatch one configured notification channel."""

    def send_to_wechat(self, content: str) -> bool:
        ...

    def send_wechat_image(self, image_bytes: bytes) -> bool:
        ...

    def send_to_feishu(self, content: str) -> bool:
        ...

    def send_to_telegram(self, content: str) -> bool:
        ...

    def send_telegram_photo(self, image_bytes: bytes) -> bool:
        ...

    def send_to_email(
        self, content: str, receivers: Optional[List[str]] = None
    ) -> bool:
        ...

    def send_email_with_inline_image(
        self, image_bytes: bytes, receivers: Optional[List[str]] = None
    ) -> bool:
        ...

    def get_all_email_receivers(self) -> List[str]:
        ...

    def get_receivers_for_stocks(self, stock_codes: List[str]) -> List[str]:
        ...

    def send_to_pushover(self, content: str) -> bool:
        ...

    def send_to_pushplus(self, content: str) -> bool:
        ...

    def send_to_serverchan3(self, content: str) -> bool:
        ...

    def send_to_custom(self, content: str) -> bool:
        ...

    def send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        ...

    def send_to_discord(self, content: str) -> bool:
        ...

    def send_to_astrbot(self, content: str) -> bool:
        ...


def _channel_value(channel: object) -> object:
    return getattr(channel, "value", channel)


def dispatch_notification_channel(
    adapter: NotificationDispatchAdapter,
    channel: object,
    content: str,
    *,
    image_bytes: Optional[bytes] = None,
    use_image: bool = False,
    email_stock_codes: Optional[List[str]] = None,
    email_send_to_all: bool = False,
) -> bool:
    """Dispatch one notification channel through the existing service adapter."""
    channel_value = _channel_value(channel)

    if channel_value == "wechat":
        if use_image and image_bytes is not None:
            return adapter.send_wechat_image(image_bytes)
        return adapter.send_to_wechat(content)

    if channel_value == "feishu":
        return adapter.send_to_feishu(content)

    if channel_value == "telegram":
        if use_image and image_bytes is not None:
            return adapter.send_telegram_photo(image_bytes)
        return adapter.send_to_telegram(content)

    if channel_value == "email":
        receivers = None
        if email_send_to_all:
            receivers = adapter.get_all_email_receivers()
        elif email_stock_codes:
            receivers = adapter.get_receivers_for_stocks(email_stock_codes)
        if use_image and image_bytes is not None:
            return adapter.send_email_with_inline_image(
                image_bytes, receivers=receivers
            )
        return adapter.send_to_email(content, receivers=receivers)

    if channel_value == "pushover":
        return adapter.send_to_pushover(content)

    if channel_value == "pushplus":
        return adapter.send_to_pushplus(content)

    if channel_value == "serverchan3":
        return adapter.send_to_serverchan3(content)

    if channel_value == "custom":
        if use_image and image_bytes is not None:
            return adapter.send_custom_webhook_image(
                image_bytes, fallback_content=content
            )
        return adapter.send_to_custom(content)

    if channel_value == "discord":
        return adapter.send_to_discord(content)

    if channel_value == "astrbot":
        return adapter.send_to_astrbot(content)

    logger.warning("不支持的通知渠道: %s", channel)
    return False
