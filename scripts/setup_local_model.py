"""Explicit, reproducible setup for free native inference on Apple Silicon Macs."""

import hashlib
import platform
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SHA = "607c79d5d6315ef9d896db83adde736a4c0057196329843544e79b95afb260a8"
MODEL_SHA = "3e4cb14174460404e7a233e531675303b2fbf7749c02f91864fe311ab6344e4f"


def download(url: str, path: Path, digest: str, limit: int) -> None:
    def checksum(file: Path) -> str:
        with file.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    if path.exists() and checksum(path) == digest:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".part")
    size = 0
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with pending.open("wb") as stream:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Download exceeded pinned artifact size limit.")
                    stream.write(chunk)
        if checksum(pending) != digest:
            raise ValueError("Artifact checksum did not match the pinned official artifact.")
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def main() -> None:
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        raise SystemExit("This setup is for Apple Silicon. Other platforms can use local Ollama.")
    archive = ROOT / ".tools/ollama-darwin.tgz"
    print("Downloading/verifying the pinned official Ollama native runtime…", flush=True)
    download(
        "https://github.com/ollama/ollama/releases/download/v0.40.15/ollama-darwin.tgz",
        archive,
        RUNTIME_SHA,
        250_000_000,
    )
    runtime = ROOT / ".tools/ollama-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(runtime, filter="data")  # safe extraction, including bundled licenses
    print("Downloading/verifying Qwen3 4B (~2.5 GB)…", flush=True)
    download(
        "https://registry.ollama.ai/v2/library/qwen3/blobs/sha256:" + MODEL_SHA,
        ROOT / ".tools/models/qwen3-4b.gguf",
        MODEL_SHA,
        2_600_000_000,
    )
    print("Ready. Set MODEL_PROVIDER=llama_cpp and MODEL_TIMEOUT_SECONDS=180 in .env.")
    print("Start CareerOS normally; it manages the local model. All files stay in .tools.")


if __name__ == "__main__":
    main()
