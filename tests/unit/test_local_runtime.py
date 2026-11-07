from unittest.mock import Mock

import httpx
import respx

from careeros.modules.models import local_runtime


def test_disabled_model_never_starts_a_process(settings, monkeypatch):  # type: ignore[no-untyped-def]
    popen = Mock()
    monkeypatch.setattr(local_runtime.subprocess, "Popen", popen)
    assert local_runtime.start(settings) is None
    popen.assert_not_called()


@respx.mock
def test_existing_authenticated_runtime_is_reused(settings, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    runtime = tmp_path / ".tools/ollama-runtime/llama-server"
    runtime.parent.mkdir(parents=True)
    runtime.touch()
    model = tmp_path / ".tools/models" / settings.llama_model
    model.parent.mkdir()
    model.touch()
    key = tmp_path / "private-key"
    key.write_text("local-test-secret")
    settings.llama_key_file = key
    settings.model_provider = "llama_cpp"
    monkeypatch.setattr(local_runtime, "ROOT", tmp_path)
    popen = Mock()
    monkeypatch.setattr(local_runtime.subprocess, "Popen", popen)
    check = respx.get("http://127.0.0.1:11435/health").mock(return_value=httpx.Response(200))
    assert local_runtime.start(settings) is None
    popen.assert_not_called()
    assert check.calls[0].request.headers["Authorization"] == "Bearer local-test-secret"


def test_only_owned_process_is_stopped():
    local_runtime.stop(None)
    process = Mock()
    process.poll.return_value = None
    local_runtime.stop(process)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
