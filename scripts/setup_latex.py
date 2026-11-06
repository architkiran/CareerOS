"""Install the pinned free Tectonic release locally and prime its offline resource cache."""

import hashlib
import io
import os
import platform
import subprocess
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.17.0"


def main() -> None:
    target = {
        ("Darwin", "arm64"): "aarch64-apple-darwin",
        ("Darwin", "x86_64"): "x86_64-apple-darwin",
        ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    }.get((platform.system(), platform.machine()))
    if target is None:
        raise SystemExit("Install Tectonic manually for this platform, then rerun setup.")
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    engine = tools / "tectonic"
    with httpx.Client(follow_redirects=True, timeout=90) as client:
        meta = client.get(
            "https://api.github.com/repos/tectonic-typesetting/tectonic/releases/tags/"
            f"tectonic%40{VERSION}"
        )
        meta.raise_for_status()
        asset = next(
            a for a in meta.json()["assets"] if a["name"] == f"tectonic-{VERSION}-{target}.tar.gz"
        )
        response = client.get(asset["browser_download_url"])
        response.raise_for_status()
        data = response.content
        if len(data) > 50_000_000:
            raise SystemExit("Compiler download exceeded its expected size.")
        expected = asset.get("digest")
        if expected and expected != "sha256:" + hashlib.sha256(data).hexdigest():
            raise SystemExit("Compiler archive digest did not match the official release metadata.")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            member = next(
                m
                for m in archive.getmembers()
                if m.isfile() and m.name.rsplit("/", 1)[-1] == "tectonic"
            )
            stream = archive.extractfile(member)
            assert stream is not None
            engine.write_bytes(stream.read())
        engine.chmod(0o755)
    warm = tools / "warmup"
    warm.mkdir(exist_ok=True)
    preamble = ROOT / "src/careeros/modules/documents/master_preamble.tex"
    (warm / "setup.tex").write_text(
        preamble.read_text() + r"\begin{document}\begin{center}{\LARGE\bfseries EXAMPLE}\\[3pt]"
        r"Example\end{center}\section{Professional Summary}Local setup."
        r"\entry{\textbf{Example} $|$ SQL}{2026}\begin{itemize}"
        r"\item Example 100\% $\sim$ 1.\end{itemize}\end{document}"
    )
    # Only this explicit setup step downloads free TeX support files. Runtime is cached-only.
    subprocess.run(  # noqa: S603 — fixed local executable and fixed warm-up content
        [str(engine), "-X", "compile", "--untrusted", "setup.tex"],
        cwd=warm,
        env={**os.environ, "TECTONIC_CACHE_DIR": str(tools / "tex-cache")},
        check=True,
        timeout=600,
    )
    print("Local compiler installed. Generate one draft to verify its fonts are cached.")


if __name__ == "__main__":
    main()
