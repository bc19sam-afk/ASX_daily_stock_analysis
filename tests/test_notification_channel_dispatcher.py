from dataclasses import dataclass
from typing import List, Optional

from src.notification_sender.channel_dispatcher import dispatch_notification_channel


CONTENT = "daily report"
IMAGE_BYTES = b"image-bytes"


@dataclass(frozen=True)
class Channel:
    value: str


class FakeDispatchAdapter:
    def __init__(self) -> None:
        self.calls = []

    def send_to_wechat(self, content: str) -> bool:
        self.calls.append(("wechat_text", content))
        return True

    def send_wechat_image(self, image_bytes: bytes) -> bool:
        self.calls.append(("wechat_image", image_bytes))
        return True

    def send_to_feishu(self, content: str) -> bool:
        self.calls.append(("feishu", content))
        return True

    def send_to_telegram(self, content: str) -> bool:
        self.calls.append(("telegram_text", content))
        return True

    def send_telegram_photo(self, image_bytes: bytes) -> bool:
        self.calls.append(("telegram_image", image_bytes))
        return True

    def send_to_email(
        self, content: str, receivers: Optional[List[str]] = None
    ) -> bool:
        self.calls.append(("email_text", content, receivers))
        return True

    def send_email_with_inline_image(
        self, image_bytes: bytes, receivers: Optional[List[str]] = None
    ) -> bool:
        self.calls.append(("email_image", image_bytes, receivers))
        return True

    def get_all_email_receivers(self) -> List[str]:
        self.calls.append(("get_all_email_receivers",))
        return ["all@example.com"]

    def get_receivers_for_stocks(self, stock_codes: List[str]) -> List[str]:
        self.calls.append(("get_receivers_for_stocks", stock_codes))
        return ["stock@example.com"]

    def send_to_pushover(self, content: str) -> bool:
        self.calls.append(("pushover", content))
        return True

    def send_to_pushplus(self, content: str) -> bool:
        self.calls.append(("pushplus", content))
        return True

    def send_to_serverchan3(self, content: str) -> bool:
        self.calls.append(("serverchan3", content))
        return True

    def send_to_custom(self, content: str) -> bool:
        self.calls.append(("custom_text", content))
        return True

    def send_custom_webhook_image(
        self, image_bytes: bytes, fallback_content: str = ""
    ) -> bool:
        self.calls.append(("custom_image", image_bytes, fallback_content))
        return True

    def send_to_discord(self, content: str) -> bool:
        self.calls.append(("discord", content))
        return True

    def send_to_astrbot(self, content: str) -> bool:
        self.calls.append(("astrbot", content))
        return True


def test_dispatch_wechat_text_and_image() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(adapter, Channel("wechat"), CONTENT)
    assert dispatch_notification_channel(
        adapter,
        Channel("wechat"),
        CONTENT,
        image_bytes=IMAGE_BYTES,
        use_image=True,
    )

    assert adapter.calls == [
        ("wechat_text", CONTENT),
        ("wechat_image", IMAGE_BYTES),
    ]


def test_dispatch_telegram_text_and_image() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(adapter, Channel("telegram"), CONTENT)
    assert dispatch_notification_channel(
        adapter,
        Channel("telegram"),
        CONTENT,
        image_bytes=IMAGE_BYTES,
        use_image=True,
    )

    assert adapter.calls == [
        ("telegram_text", CONTENT),
        ("telegram_image", IMAGE_BYTES),
    ]


def test_dispatch_email_default_receivers() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(adapter, Channel("email"), CONTENT)

    assert adapter.calls == [("email_text", CONTENT, None)]


def test_dispatch_email_send_to_all_receivers() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(
        adapter,
        Channel("email"),
        CONTENT,
        email_send_to_all=True,
    )

    assert adapter.calls == [
        ("get_all_email_receivers",),
        ("email_text", CONTENT, ["all@example.com"]),
    ]


def test_dispatch_email_stock_receivers_and_image() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(
        adapter,
        Channel("email"),
        CONTENT,
        image_bytes=IMAGE_BYTES,
        use_image=True,
        email_stock_codes=["BHP", "CBA"],
    )

    assert adapter.calls == [
        ("get_receivers_for_stocks", ["BHP", "CBA"]),
        ("email_image", IMAGE_BYTES, ["stock@example.com"]),
    ]


def test_dispatch_custom_text_and_image() -> None:
    adapter = FakeDispatchAdapter()

    assert dispatch_notification_channel(adapter, Channel("custom"), CONTENT)
    assert dispatch_notification_channel(
        adapter,
        Channel("custom"),
        CONTENT,
        image_bytes=IMAGE_BYTES,
        use_image=True,
    )

    assert adapter.calls == [
        ("custom_text", CONTENT),
        ("custom_image", IMAGE_BYTES, CONTENT),
    ]


def test_dispatch_basic_text_channels() -> None:
    adapter = FakeDispatchAdapter()

    for channel in [
        "feishu",
        "pushover",
        "pushplus",
        "serverchan3",
        "discord",
        "astrbot",
    ]:
        assert dispatch_notification_channel(adapter, Channel(channel), CONTENT)

    assert adapter.calls == [
        ("feishu", CONTENT),
        ("pushover", CONTENT),
        ("pushplus", CONTENT),
        ("serverchan3", CONTENT),
        ("discord", CONTENT),
        ("astrbot", CONTENT),
    ]


def test_dispatch_unknown_channel_returns_false() -> None:
    adapter = FakeDispatchAdapter()

    assert not dispatch_notification_channel(adapter, Channel("unknown"), CONTENT)

    assert adapter.calls == []
