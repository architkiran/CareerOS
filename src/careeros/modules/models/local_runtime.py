"""Manage optional project-local inference; never download or use cloud APIs at startup."""

import logging
import os
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from careeros.config import Settings

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[4]


def start(settings: Settings) -> subprocess.Popen[bytes] | None:
    if settings.model_provider != "llama_cpp":
        return None
    url = urlsplit(settings.llama_base_url)
    if url.hostname != "127.0.0.1" or url.port != 11435:
        logger.warning("Custom local inference endpoint must be started separately.")
        return None
    runtime = ROOT / ".tools/ollama-runtime/llama-server"
    model = ROOT / ".tools/models" / settings.llama_model
    if not runtime.is_file() or not model.is_file():
        logger.warning("Local rewrite runtime or model missing. See docs/LOCAL_REWRITES.md.")
        return None
    key_path = settings.llama_key_file
    if not key_path.is_absolute():
        key_path = ROOT / key_path
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as key:
            key.write(secrets.token_urlsafe(32))
        key_path.chmod(0o600)
    headers = {"Authorization": "Bearer " + key_path.read_text().strip()}
    with httpx.Client(trust_env=False, timeout=1) as client:
        try:
            if client.get(settings.llama_base_url + "/health", headers=headers).status_code == 200:
                return None  # Existing service is not ours to stop.
        except httpx.HTTPError:
            pass
        log_path = ROOT / ".tools/local-model.log"
        with log_path.open("ab") as log:
            process = subprocess.Popen(  # noqa: S603 — fixed project-local executable, no shell
                [
                    str(runtime),
                    "-m",
                    str(model),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "11435",
                    "-c",
                    "8192",
                    "-np",
                    "1",
                    "--reasoning",
                    "off",
                    "--reasoning-budget",
                    "0",
                    "--api-key-file",
                    str(key_path),
                    "--cors-origins",
                    f"http://127.0.0.1:{settings.app_port}",
                    "-t",
                    "4",
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        log_path.chmod(0o600)
        for _ in range(60):
            if process.poll() is not None:
                logger.warning("Local model startup failed. Inspect .tools/local-model.log.")
                return None
            try:
                if (
                    client.get(settings.llama_base_url + "/health", headers=headers).status_code
                    == 200
                ):
                    logger.info("Project-local resume model is ready.")
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        stop(process)
        logger.warning("Local model startup timed out; manual resume editing is available.")
    return None


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
