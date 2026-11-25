"""Tests for the photo review service and CLI.

Every test runs offline: gateway responses are synthesized with
``httpx.MockTransport``, images are drawn into ``tmp_path``, and configuration
is passed as a literal mapping. No test reads or mutates ``os.environ``.
"""

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.services.photo_review import (
    DATA_URI_PREFIX,
    DEFAULT_REVIEW_PROMPT,
    PhotoReviewer,
    ReviewConfig,
    ReviewConfigError,
    probe_gateway,
    warmup_model,
)
from script import review as script_review

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_ENV = {
    "OPENAI_BASE_URL": "http://gateway.local/v1",
    "OPENAI_API_KEY": "sk-test",
    "OPENAI_MODEL": "test-model",
}

ORIENTATION_TAG = 0x0112


# --- helpers ---------------------------------------------------------------


def _make_image(path, size, mode="RGB", color=None, orientation=None):
    """Draw a synthetic image at *path* and optionally tag EXIF orientation."""
    if color is None:
        color = (120, 180, 240) if mode == "RGB" else (120, 180, 240, 255)
    image = Image.new(mode, size, color)
    if orientation is not None:
        exif = Image.Exif()
        exif[ORIENTATION_TAG] = orientation
        image.save(path, exif=exif)
    else:
        image.save(path)
    return path


def _ok_body(content="  很棒的一张照片。  "):
    return {"choices": [{"message": {"content": content}}]}


class _Recorder:
    """MockTransport handler that records requests and replays responses."""

    def __init__(self, responses=None):
        self.requests = []
        self._responses = list(responses or [])

    def __call__(self, request):
        self.requests.append(request)
        if not self._responses:
            return httpx.Response(200, json=_ok_body())
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _client(recorder):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(recorder), timeout=None
    )


async def _review(path, recorder, model="test-model"):
    async with _client(recorder) as client:
        reviewer = PhotoReviewer(
            "http://gateway.local/v1",
            "sk-test",
            model,
            http_client=client,
        )
        return await reviewer.review(str(path))


def _image_url_from(request):
    payload = json.loads(request.content)
    parts = payload["messages"][0]["content"]
    return next(part["image_url"]["url"] for part in parts if part["type"] == "image_url")


def _decode_data_uri(uri):
    assert uri.startswith(DATA_URI_PREFIX)
    raw = base64.b64decode(uri[len(DATA_URI_PREFIX):])
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image.size, image.mode, image.format


# --- configuration ---------------------------------------------------------


def test_config_reads_all_required_values():
    config = ReviewConfig.from_env(CONFIG_ENV)

    assert config.base_url == "http://gateway.local/v1"
    assert config.api_key == "sk-test"
    assert config.model == "test-model"


def test_config_strips_surrounding_whitespace_and_trailing_slash():
    config = ReviewConfig.from_env(
        {
            **CONFIG_ENV,
            "OPENAI_BASE_URL": " http://gateway.local/v1/ ",
            "OPENAI_MODEL": " test-model ",
        }
    )

    assert config.base_url == "http://gateway.local/v1"
    assert config.model == "test-model"


@pytest.mark.parametrize("name", sorted(CONFIG_ENV))
def test_config_reports_missing_variable(name):
    env = {key: value for key, value in CONFIG_ENV.items() if key != name}

    with pytest.raises(ReviewConfigError) as excinfo:
        ReviewConfig.from_env(env)

    assert name in str(excinfo.value)


@pytest.mark.parametrize("name", sorted(CONFIG_ENV))
def test_config_treats_blank_value_as_missing(name):
    with pytest.raises(ReviewConfigError) as excinfo:
        ReviewConfig.from_env({**CONFIG_ENV, name: "   "})

    assert name in str(excinfo.value)


def test_config_model_override_wins_over_environment():
    merged = {**CONFIG_ENV, "OPENAI_MODEL": "cli-model"}

    assert ReviewConfig.from_env(merged).model == "cli-model"


# --- image preparation -----------------------------------------------------


@pytest.mark.asyncio
async def test_landscape_photo_is_scaled_to_1024_by_768(tmp_path):
    path = _make_image(tmp_path / "landscape.jpg", (4032, 3024))
    recorder = _Recorder()

    text = await _review(path, recorder)

    assert text == "很棒的一张照片。"
    size, mode, image_format = _decode_data_uri(_image_url_from(recorder.requests[0]))
    assert size == (1024, 768)
    assert mode == "RGB"
    assert image_format == "JPEG"


@pytest.mark.asyncio
async def test_portrait_photo_is_scaled_by_long_edge(tmp_path):
    path = _make_image(tmp_path / "portrait.jpg", (3024, 4032))
    recorder = _Recorder()

    await _review(path, recorder)

    size, _, _ = _decode_data_uri(_image_url_from(recorder.requests[0]))
    assert size == (768, 1024)


@pytest.mark.asyncio
async def test_small_photo_is_not_upscaled(tmp_path):
    path = _make_image(tmp_path / "small.jpg", (800, 600))
    recorder = _Recorder()

    await _review(path, recorder)

    size, _, _ = _decode_data_uri(_image_url_from(recorder.requests[0]))
    assert size == (800, 600)


@pytest.mark.asyncio
async def test_exif_orientation_is_applied(tmp_path):
    path = _make_image(
        tmp_path / "rotated.jpg", (4000, 3000), orientation=6
    )
    recorder = _Recorder()

    await _review(path, recorder)

    size, _, _ = _decode_data_uri(_image_url_from(recorder.requests[0]))
    assert size == (768, 1024)


@pytest.mark.asyncio
async def test_transparent_png_becomes_opaque_jpeg(tmp_path):
    path = _make_image(
        tmp_path / "alpha.png", (300, 200), mode="RGBA", color=(255, 0, 0, 0)
    )
    recorder = _Recorder()

    await _review(path, recorder)

    size, mode, image_format = _decode_data_uri(_image_url_from(recorder.requests[0]))
    assert size == (300, 200)
    assert mode == "RGB"
    assert image_format == "JPEG"


# --- request shape ---------------------------------------------------------


@pytest.mark.asyncio
async def test_request_targets_chat_completions_with_bearer_auth(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (640, 480))
    recorder = _Recorder()

    await _review(path, recorder)

    request = recorder.requests[0]
    assert str(request.url) == "http://gateway.local/v1/chat/completions"
    assert request.method == "POST"
    assert request.headers["authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_request_carries_prompt_and_image_in_one_user_message(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (640, 480))
    recorder = _Recorder()

    await _review(path, recorder)

    payload = json.loads(recorder.requests[0].content)
    assert payload["model"] == "test-model"
    assert payload["reasoning_effort"] == "none"
    assert len(payload["messages"]) == 1
    message = payload["messages"][0]
    assert message["role"] == "user"
    parts = message["content"]
    text_part = next(part for part in parts if part["type"] == "text")
    image_part = next(part for part in parts if part["type"] == "image_url")
    assert text_part["text"] == DEFAULT_REVIEW_PROMPT
    assert image_part["image_url"]["url"].startswith(DATA_URI_PREFIX)


@pytest.mark.asyncio
async def test_injected_client_is_not_closed(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (640, 480))
    async with _client(_Recorder()) as client:
        reviewer = PhotoReviewer(
            "http://gateway.local/v1", "sk-test", "test-model", http_client=client
        )

        await reviewer.review(str(path))

        assert not client.is_closed


# --- result parsing --------------------------------------------------------


@pytest.mark.asyncio
async def test_result_is_stripped(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    text = await _review(path, _Recorder([httpx.Response(200, json=_ok_body("\n 好看。\n"))]))

    assert text == "好看。"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "   ", None, 123])
async def test_unusable_content_degrades_to_none(tmp_path, content):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    body = {"choices": [{"message": {"content": content}}]}

    text = await _review(path, _Recorder([httpx.Response(200, json=body)]))

    assert text is None


# --- failure degradation ---------------------------------------------------


@pytest.mark.asyncio
async def test_server_error_degrades_to_none(tmp_path, caplog):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        text = await _review(
            path, _Recorder([httpx.Response(500, text="upstream exploded")])
        )

    assert text is None
    assert "500" in caplog.text
    assert "sk-test" not in caplog.text


@pytest.mark.asyncio
async def test_non_json_response_degrades_to_none(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    text = await _review(
        path, _Recorder([httpx.Response(200, text="<html>bad gateway</html>")])
    )

    assert text is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ["not", "text"]}}]},
    ],
)
async def test_malformed_payload_degrades_to_none(tmp_path, body):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    text = await _review(path, _Recorder([httpx.Response(200, json=body)]))

    assert text is None


@pytest.mark.asyncio
async def test_connection_error_degrades_to_none(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    text = await _review(
        path, _Recorder([httpx.ConnectError("connection refused")])
    )

    assert text is None


@pytest.mark.asyncio
async def test_undecodable_file_skips_the_request(tmp_path):
    path = tmp_path / "not-an-image.jpg"
    path.write_text("this is plain text, not a JPEG")
    recorder = _Recorder()

    text = await _review(path, recorder)

    assert text is None
    assert recorder.requests == []


# --- CLI adapter -----------------------------------------------------------


class _FakeReviewer:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def review(self, image_path):
        self.calls.append(image_path)
        return self.text


class _RecordingFactory:
    """Callable that stands in for PhotoReviewer and records its arguments."""

    def __init__(self, text="很棒的一张照片。"):
        self.text = text
        self.kwargs = {}
        self.reviewer = None

    def __call__(self, base_url, api_key, model):
        self.kwargs = {"base_url": base_url, "api_key": api_key, "model": model}
        self.reviewer = _FakeReviewer(self.text)
        return self.reviewer


def _clean_env(**overrides):
    """Build a subprocess environment without OPENAI_* leakage or .env loading.

    ``PYTHON_DOTENV_DISABLED`` keeps the child hermetic: ``load_dotenv()``
    searches upward from ``script/review.py``, so it would otherwise read the
    developer's real ``.env`` and make these assertions depend on local setup.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("OPENAI_")}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env.update(overrides)
    return env


def _run_cli(args, env, cwd):
    return subprocess.run(
        [sys.executable, "-m", "script.review", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def test_cli_without_arguments_exits_with_usage_error(tmp_path):
    result = _run_cli([], _clean_env(), tmp_path)

    assert result.returncode == 2
    assert "usage" in result.stderr.lower()


def test_cli_missing_api_key_exits_with_config_error(tmp_path):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    env = _clean_env(
        OPENAI_BASE_URL="http://gateway.local/v1",
        OPENAI_MODEL="test-model",
    )

    result = _run_cli([str(path)], env, tmp_path)

    assert result.returncode == 2
    assert "OPENAI_API_KEY" in result.stderr
    assert result.stdout == ""


def test_cli_importing_service_does_not_touch_environment(tmp_path):
    code = (
        "import os\n"
        "before = dict(os.environ)\n"
        "import app.services.photo_review\n"
        "after = dict(os.environ)\n"
        "assert before == after\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=_clean_env(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_cli_success_prints_only_the_review(tmp_path, capsys):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    factory = _RecordingFactory("构图精巧，光影温柔。")

    code = script_review.main([str(path)], env=CONFIG_ENV, review_factory=factory)

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "构图精巧，光影温柔。\n"
    assert captured.err == ""
    assert factory.reviewer.calls == [str(path)]


def test_cli_model_option_overrides_environment(tmp_path, capsys):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    factory = _RecordingFactory()

    code = script_review.main(
        ["--model", "cli-model", str(path)],
        env=CONFIG_ENV,
        review_factory=factory,
    )

    capsys.readouterr()
    assert code == 0
    assert factory.kwargs["model"] == "cli-model"
    assert factory.kwargs["base_url"] == "http://gateway.local/v1"


def test_cli_review_failure_exits_with_one(tmp_path, capsys):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    factory = _RecordingFactory(None)

    code = script_review.main([str(path)], env=CONFIG_ENV, review_factory=factory)

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "点评失败" in captured.err


def test_cli_missing_config_reports_all_missing_names(tmp_path, capsys):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))

    code = script_review.main([str(path)], env={}, review_factory=_RecordingFactory())

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    for name in CONFIG_ENV:
        assert name in captured.err


def test_cli_unreadable_path_exits_with_one(tmp_path, capsys):
    factory = _RecordingFactory()

    code = script_review.main(
        [str(tmp_path / "missing.jpg")], env=CONFIG_ENV, review_factory=factory
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "不可读" in captured.err
    assert factory.reviewer is None


def test_cli_leaves_input_and_directory_untouched(tmp_path, capsys):
    path = _make_image(tmp_path / "photo.jpg", (320, 240))
    original_bytes = path.read_bytes()
    original_mtime = path.stat().st_mtime_ns
    original_entries = sorted(entry.name for entry in tmp_path.iterdir())

    code = script_review.main(
        [str(path)], env=CONFIG_ENV, review_factory=_RecordingFactory()
    )

    capsys.readouterr()
    assert code == 0
    assert path.read_bytes() == original_bytes
    assert path.stat().st_mtime_ns == original_mtime
    assert sorted(entry.name for entry in tmp_path.iterdir()) == original_entries


# --- optional configuration (message-chain entry) --------------------------


def test_config_optional_returns_config_when_complete():
    config = ReviewConfig.from_env_optional(CONFIG_ENV)

    assert config is not None
    assert config.base_url == "http://gateway.local/v1"
    assert config.api_key == "sk-test"
    assert config.model == "test-model"


@pytest.mark.parametrize("name", ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
def test_config_optional_returns_none_when_missing(name):
    env = {key: value for key, value in CONFIG_ENV.items() if key != name}

    assert ReviewConfig.from_env_optional(env) is None


@pytest.mark.parametrize("name", ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
def test_config_optional_returns_none_when_blank(name):
    env = {**CONFIG_ENV, name: "   "}

    assert ReviewConfig.from_env_optional(env) is None


def test_config_optional_does_not_swallow_unexpected_errors():
    class Exploding(dict):
        def get(self, key, default=None):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        ReviewConfig.from_env_optional(Exploding())


# --- startup availability probe -------------------------------------------


def _models_body(*model_ids):
    """Build an OpenAI-shaped /models payload."""
    return {
        "object": "list",
        "data": [{"id": model_id, "object": "model"} for model_id in model_ids],
    }


def test_probe_ready_when_model_listed(caplog):
    recorder = _Recorder([httpx.Response(200, json=_models_body("qwen3.5:9b"))])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "qwen3.5:9b")

    with caplog.at_level(logging.INFO, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is True
    assert probe.models == ("qwen3.5:9b",)
    request = recorder.requests[0]
    assert request.method == "GET"
    assert request.url.raw_path == b"/v1/models"
    assert request.headers["authorization"] == "Bearer sk-test"
    assert "health OK" in caplog.text
    assert "present=yes" in caplog.text
    assert "sk-test" not in caplog.text


def test_probe_not_ready_when_model_missing(caplog):
    recorder = _Recorder([httpx.Response(200, json=_models_body("other-model"))])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "missing")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.reachable is True
    assert probe.model_present is False
    assert "present=no" in caplog.text


def test_probe_not_ready_for_empty_model_list(caplog):
    recorder = _Recorder([httpx.Response(200, json=_models_body())])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.models == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "list", "data": []},
        {"object": "list"},
        {"data": "not-a-list"},
        ["not-an-object"],
    ],
)
def test_probe_not_ready_for_unparsable_payload(payload, caplog):
    recorder = _Recorder([httpx.Response(200, json=payload)])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.reachable is True
    assert "health FAILED" in caplog.text


def test_probe_not_ready_for_invalid_json(caplog):
    recorder = _Recorder([httpx.Response(200, content=b"not json")])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.reachable is True
    assert probe.models == ()


def test_probe_skips_entries_without_id(caplog):
    recorder = _Recorder(
        [httpx.Response(200, json={"data": [{"object": "model"}, {"id": "test-model"}]})]
    )
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.INFO, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is True
    assert probe.models == ("test-model",)


def test_probe_reports_non_success_status(caplog):
    recorder = _Recorder([httpx.Response(403, json={"error": {"message": "forbidden"}})])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.status == 403
    assert "status=403" in caplog.text


def test_probe_reports_connection_failure(caplog):
    recorder = _Recorder([httpx.ConnectError("connection refused")])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        probe = asyncio.run(_probe(config, recorder))

    assert probe.ready is False
    assert probe.reachable is False
    assert "ConnectError" in caplog.text
    assert "sk-test" not in caplog.text


async def _probe(config, recorder):
    async with _client(recorder) as client:
        return await probe_gateway(config, http_client=client)


# --- cold-disk model warmup -------------------------------------------------


async def _warmup(config, recorder, **kwargs):
    async with _client(recorder) as client:
        await warmup_model(config, http_client=client, **kwargs)


def test_warmup_sends_minimal_chat_request():
    recorder = _Recorder([httpx.Response(200, json=_ok_body("ok"))])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    asyncio.run(_warmup(config, recorder))

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.raw_path == b"/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 1
    assert body["messages"] == [{"role": "user", "content": "ping"}]
    assert body["reasoning_effort"] == "none"


def test_warmup_success_stays_below_info(caplog):
    recorder = _Recorder([httpx.Response(200, json=_ok_body("ok"))])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.INFO, logger="file-bridge.review"):
        asyncio.run(_warmup(config, recorder))

    assert "warmup" not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
def test_warmup_failure_logs_one_warning_and_never_raises(response, caplog):
    recorder = _Recorder([response])
    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    with caplog.at_level(logging.WARNING, logger="file-bridge.review"):
        asyncio.run(_warmup(config, recorder))

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "warmup FAILED" in caplog.text
    assert "sk-test" not in caplog.text


def test_warmup_dedupes_concurrent_requests():
    requests = []

    async def handler(request):
        requests.append(request)
        # Yield so the first request stays in flight while the rest arrive.
        await asyncio.sleep(0)
        return httpx.Response(200, json=_ok_body("ok"))

    config = ReviewConfig("http://gateway.local/v1", "sk-test", "test-model")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=None
        ) as client:
            await asyncio.gather(
                warmup_model(config, http_client=client),
                warmup_model(config, http_client=client),
                warmup_model(config, http_client=client),
            )

    asyncio.run(run())

    assert len(requests) == 1

