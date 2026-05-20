import base64
from types import SimpleNamespace

from google import genai

from src.services import image_stock_extractor


def test_gemini_image_extractor_uses_configured_gemini_3_model(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return SimpleNamespace(text='["BHP.AX"]')

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(
        image_stock_extractor,
        "get_config",
        lambda: SimpleNamespace(
            gemini_api_key=None,
            gemini_api_keys=["vision-key-1234567890"],
            gemini_model="gemini-3-flash-preview",
        ),
    )

    raw = image_stock_extractor._call_gemini(
        base64.b64encode(b"image-bytes").decode("ascii"),
        "image/png",
    )

    assert raw == '["BHP.AX"]'
    assert captured["model"] == "gemini-3-flash-preview"
    assert captured["client_kwargs"]["api_key"] == "vision-key-1234567890"
    assert captured["client_kwargs"]["http_options"].timeout == 60000
    assert len(captured["contents"]) == 2


def test_gemini_image_extractor_defaults_to_gemini_3_5_model(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, *, model, contents):
            captured["model"] = model
            return SimpleNamespace(text='["CBA.AX"]')

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(
        image_stock_extractor,
        "get_config",
        lambda: SimpleNamespace(
            gemini_api_key=None,
            gemini_api_keys=["vision-key-1234567890"],
            gemini_model="",
            gemini_model_fallback="",
        ),
    )

    raw = image_stock_extractor._call_gemini(
        base64.b64encode(b"image-bytes").decode("ascii"),
        "image/png",
    )

    assert raw == '["CBA.AX"]'
    assert captured["model"] == "gemini-3.5-flash"


def test_gemini_image_extractor_tries_configured_fallback_model(monkeypatch):
    calls = []

    class FakeModels:
        def generate_content(self, *, model, contents):
            calls.append(model)
            if model == "gemini-3.5-flash":
                raise RuntimeError("primary model unavailable")
            return SimpleNamespace(text='["CSL.AX"]')

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(
        image_stock_extractor,
        "get_config",
        lambda: SimpleNamespace(
            gemini_api_key=None,
            gemini_api_keys=["vision-key-1234567890"],
            gemini_model="gemini-3.5-flash",
            gemini_model_fallback="gemini-3-flash-preview",
        ),
    )

    raw = image_stock_extractor._call_gemini(
        base64.b64encode(b"image-bytes").decode("ascii"),
        "image/png",
    )

    assert raw == '["CSL.AX"]'
    assert calls == ["gemini-3.5-flash", "gemini-3-flash-preview"]
