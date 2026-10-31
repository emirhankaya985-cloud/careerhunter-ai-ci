"""Checksum-pinned, rootless PostgreSQL 17 client for owner-only restore tests.

Downloads official PGDG Debian 12 packages into an ephemeral directory.
No system libraries or production application processes are modified.
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(tempfile.gettempdir()) / "careerhunter-pg17-client"
BASE = "https://apt.postgresql.org/pub/repos/apt/pool/main/p/"
PACKAGES = (
    ("postgresql-17/postgresql-client-17_17.11-1.pgdg12+2_amd64.deb",
     "1e286c060f8f9ab6485b1b02df6543ce38610bc828c63695528f0593658113ed"),
    ("postgresql-18/libpq5_18.6-3.pgdg12+1_amd64.deb",
     "af24a85e9d856c6339b55251d059cd52c23dbda103f5caf6a4050c512573d102"),
)


def binary_path(binary: str) -> str | None:
    if binary not in ("pg_dump", "pg_restore"):
        raise ValueError("Unexpected executable")
    path = ROOT / "usr/lib/postgresql/17/bin" / binary
    return str(path) if path.is_file() else None


def command_env(original: dict[str, str]) -> dict[str, str]:
    env = dict(original)
    lib = ROOT / "usr/lib/x86_64-linux-gnu"
    if lib.is_dir():
        env["LD_LIBRARY_PATH"] = str(lib) + (
            ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
        )
    return env


def _fetch(relative: str, expected_sha256: str, output: Path) -> None:
    uri = BASE + relative
    req = Request(uri, headers={"User-Agent": "CareerHunter-PG17-Verification/1.0"})
    with urlopen(req, timeout=35) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "apt.postgresql.org":
            raise RuntimeError("Unexpected package download host")
        content = response.read(3_000_001)
    if not content or len(content) > 3_000_000:
        raise RuntimeError("PG17 package size invalid")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise RuntimeError("PG17 package checksum mismatch")
    output.write_bytes(content)


def install() -> None:
    if platform.machine() != "x86_64" or not shutil.which("dpkg-deb"):
        raise RuntimeError("Unsupported PG17 execution platform")
    with tempfile.TemporaryDirectory(prefix="careerhunter-pg17-fetch-") as directory:
        tmp = Path(directory)
        for index, (path, digest) in enumerate(PACKAGES):
            archive = tmp / f"client-{index}.deb"
            _fetch(path, digest, archive)
            ROOT.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["dpkg-deb", "-x", str(archive), str(ROOT)],
                timeout=25, check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    env = command_env(os.environ)
    for binary in ("pg_dump", "pg_restore"):
        executable = binary_path(binary)
        if not executable:
            raise RuntimeError("PG17 executable missing after verified extraction")
        check = subprocess.run(
            [executable, "--version"], env=env, timeout=8, check=True,
            capture_output=True, text=True,
        )
        if "PostgreSQL) 17." not in check.stdout:
            raise RuntimeError("PG17 version validation failed")
