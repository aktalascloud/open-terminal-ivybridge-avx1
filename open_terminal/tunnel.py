"""Opt-in Cloudflare Quick Tunnels and a pinned, verified connector installer."""

import asyncio
from collections import deque
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

import click
import httpx
import uvicorn


CLOUDFLARED_VERSION = "2026.10.3"
RELEASE_BASE = "https://github.com/cloudflare/cloudflared/releases/download"
LICENSE_URL = "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/license/"
TERMS_URL = "https://www.cloudflare.com/website-terms/"
MAX_DOWNLOAD = 128 * 1024 * 1024
DOWNLOAD_TIMEOUT = 120
STARTUP_TIMEOUT = 30
TUNNEL_TIMEOUT = 60
STOP_TIMEOUT = 5


@dataclass(frozen=True)
class Asset:
    name: str
    sha256: str
    binary_sha256: str


# Pin both layers: the macOS release-note checksums describe the inner executable.
ASSETS = {
    ("Darwin", "amd64"): Asset(
        "cloudflared-darwin-amd64.tgz",
        "81b7b85f2376815c4f59b1aa323887b62e16ce8b67555c2e1577dc23f2a82000",
        "947e2942d6a59922d80190d23b12f3ade8da16e23e3bd937182a48993b7c00db",
    ),
    ("Darwin", "arm64"): Asset(
        "cloudflared-darwin-arm64.tgz",
        "1165d14b6f6360a3b8c283d7d1100024d6ec7cd9bc9e32519e96150645f3ec55",
        "f249139e0541fa589c987397d867cc16c83ab1236d31eb6782f2e4552ee9cf80",
    ),
    ("Linux", "amd64"): Asset(
        "cloudflared-linux-amd64",
        "053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0",
        "053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0",
    ),
    ("Linux", "arm64"): Asset(
        "cloudflared-linux-arm64",
        "89297ebfb9e8c99c0dc013a1140601453cf3798d8306c5591651f4a3f5210be8",
        "89297ebfb9e8c99c0dc013a1140601453cf3798d8306c5591651f4a3f5210be8",
    ),
    ("Windows", "amd64"): Asset(
        "cloudflared-windows-amd64.exe",
        "76b2805253d0d6ffacb092a7acfbee99e7af6917835c0c5410e23f3ef5052da2",
        "76b2805253d0d6ffacb092a7acfbee99e7af6917835c0c5410e23f3ef5052da2",
    ),
}


def cache_root(system: str) -> Path:
    if system == "Darwin":
        return Path.home() / "Library/Caches/open-terminal"
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "open-terminal/Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "open-terminal"


def verified(path: Path, expected: str) -> bool:
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == expected
    except OSError:
        return False


async def _https_only(request: httpx.Request):
    if request.url.scheme != "https":
        raise ValueError("cloudflared downloads must use HTTPS, including redirects")


async def _download(url: str, target: Path, expected: str):
    digest = hashlib.sha256()
    size = 0
    async with asyncio.timeout(DOWNLOAD_TIMEOUT):
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            event_hooks={"request": [_https_only]},
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise ValueError("cloudflared download exceeds 128 MiB")
                        digest.update(chunk)
                        output.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("cloudflared release checksum mismatch; nothing was installed")


def install(asset: Asset, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{RELEASE_BASE}/{CLOUDFLARED_VERSION}/{asset.name}"
    with tempfile.TemporaryDirectory(prefix=".cloudflared-", dir=destination.parent) as work:
        downloaded = Path(work) / "download"
        executable = Path(work) / "executable"
        asyncio.run(_download(url, downloaded, asset.sha256))
        if asset.name.endswith(".tgz"):
            with tarfile.open(downloaded, "r:gz") as archive:
                found = False
                for member in archive:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts or "\\" in member.name or not member.isfile():
                        raise ValueError("Unsafe cloudflared archive member")
                    if path.as_posix() != "cloudflared" or found:
                        raise ValueError("Unexpected cloudflared archive member")
                    if member.size > MAX_DOWNLOAD:
                        raise ValueError("cloudflared executable exceeds 128 MiB")
                    with archive.extractfile(member) as source, executable.open("wb") as output:
                        shutil.copyfileobj(source, output, length=64 * 1024)
                    found = True
                if not found:
                    raise ValueError("cloudflared archive contains no executable")
        else:
            downloaded.rename(executable)
        if not verified(executable, asset.binary_sha256):
            raise ValueError("cloudflared executable checksum mismatch; nothing was installed")
        executable.chmod(0o700)
        # Another launch may have finished the same installation while we downloaded.
        if not verified(destination, asset.binary_sha256) or not os.access(destination, os.X_OK):
            os.replace(executable, destination)
    return destination


def resolve_binary(yes: bool = False) -> Path:
    installed = shutil.which("cloudflared")
    if installed:
        return Path(installed)
    system = platform.system()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "x64": "amd64", "aarch64": "arm64"}.get(machine, machine)
    asset = ASSETS.get((system, arch))
    if asset is None:
        raise click.ClickException(f"No managed cloudflared build for {system}/{machine}. Install cloudflared on PATH.")
    destination = cache_root(system) / "cloudflared" / CLOUDFLARED_VERSION / f"{system.lower()}-{arch}" / (
        "cloudflared.exe" if system == "Windows" else "cloudflared"
    )
    if verified(destination, asset.binary_sha256) and os.access(destination, os.X_OK):
        return destination
    url = f"{RELEASE_BASE}/{CLOUDFLARED_VERSION}/{asset.name}"
    if not yes:
        if not sys.stdin.isatty():
            raise click.ClickException("cloudflared is not installed or its cache is invalid. Use --cftunnel --yes to authorize a download, or install cloudflared on PATH.")
        click.echo(f"Download cloudflared {CLOUDFLARED_VERSION} from {url}\nLicense: {LICENSE_URL}\nTerms: {TERMS_URL}")
        if not click.confirm("Download and install this verified executable?", default=False):
            raise click.ClickException("cloudflared download declined; server was not started.")
    click.echo(f"Downloading cloudflared {CLOUDFLARED_VERSION}…")
    try:
        return install(asset, destination)
    except (OSError, ValueError, httpx.HTTPError, tarfile.TarError, TimeoutError) as exc:
        raise click.ClickException(f"Could not install cloudflared: {exc}") from exc


def origin_url(host: str, port: int) -> str:
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def assigned_url(line: str) -> str | None:
    for match in re.finditer(r"https://([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.trycloudflare\.com(?=$|[\s/|])", line):
        if match[1] != "api":
            return match[0]
    return None


def child_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("OPEN_TERMINAL_", "TUNNEL_", "CLOUDFLARED_"))
        and key.upper() not in {"NO_AUTOUPDATE", "NO_TLS_VERIFY"}
    }


class Tunnel:
    """One connector process; its reader keeps pipes drained for its entire life."""

    def __init__(self, binary: Path, origin: str, config: Path):
        self.url = None
        self.connected = False
        self.logs = deque(maxlen=50)
        # This HTTP API needs no UDP routing; HTTP/2 also works on networks blocking QUIC.
        try:
            self.process = subprocess.Popen(
                [str(binary), "tunnel", "--no-autoupdate", "--config", str(config),
                 "--url", origin, "--protocol", "http2",
                 "--loglevel", "info", "--metrics", "127.0.0.1:0"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=child_environment(), shell=False,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as exc:
            raise RuntimeError(f"Could not start cloudflared: {exc}. Check executable permissions; update or remove an incompatible installation on PATH.") from exc
        self.reader = threading.Thread(target=self._read, name="cloudflared-output")
        try:
            self.reader.start()
        except BaseException:
            self.close()
            raise

    def _read(self):
        for raw in iter(lambda: self.process.stdout.readline(8192), b""):
            line = raw.decode("utf-8", errors="replace").strip()
            self.logs.append(line)
            if "Registered tunnel connection" in line:
                self.connected = True
            if self.url is None:
                self.url = assigned_url(line)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        if self.reader.ident is not None:
            self.reader.join()
        self.process.stdout.close()


class TunnelServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await asyncio.wait_for(super().startup(sockets=sockets), timeout=STARTUP_TIMEOUT)

    async def shutdown(self, sockets=None):
        # Uvicorn re-raises SIGTERM after shutdown, which can bypass outer finally blocks.
        await asyncio.to_thread(self.stop_tunnel)
        await super().shutdown(sockets=sockets)


def run_server(binary: Path, host: str, port: int, **options):
    server = TunnelServer(uvicorn.Config("open_terminal.main:app", host=host, port=port, **options))
    stopped = threading.Event()
    failure = []

    def stopping():
        return stopped.is_set() or server.should_exit

    def supervise():
        tunnel = None
        try:
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while not server.started:
                if stopping():
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError("Local server startup timed out")
                stopped.wait(0.05)
            if stopping():
                return
            with tempfile.TemporaryDirectory(prefix="open-terminal-tunnel-") as work:
                config = Path(work) / "config.yml"
                config.write_text("{}\n", encoding="utf-8")
                try:
                    click.echo("Starting public tunnel…")
                    tunnel = Tunnel(binary, origin_url(host, port), config)
                    deadline = time.monotonic() + TUNNEL_TIMEOUT
                    ready = False
                    last_check = "Waiting for cloudflared to publish its URL."
                    with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                        while not stopping():
                            code = tunnel.process.poll()
                            if code is not None:
                                raise RuntimeError(f"cloudflared exited with code {code}. Update the executable on PATH if it is incompatible.")
                            if not ready:
                                if tunnel.url and not tunnel.connected:
                                    last_check = "Waiting for cloudflared to register its connection."
                                if time.monotonic() >= deadline:
                                    raise RuntimeError(f"Public tunnel did not become ready within {TUNNEL_TIMEOUT} seconds. {last_check}")
                                # Avoid caching NXDOMAIN while Cloudflare is still provisioning.
                                if tunnel.url and tunnel.connected:
                                    try:
                                        response = client.get(f"{tunnel.url}/health")
                                        last_check = f"Health check returned HTTP {response.status_code} with an unexpected response."
                                        ready = response.status_code == 200 and response.json() == {"status": "ok"}
                                    except (httpx.HTTPError, ValueError) as exc:
                                        last_check = f"Health check failed: {str(exc)[:1000]}"
                                    if ready and not stopping():
                                        click.echo(f"  Public:  {tunnel.url}\n  Auth:    Use your configured Open Terminal API key\n\nTemporary public access is active. Press Ctrl+C to stop.")
                            stopped.wait(0.1 if ready else 0.25)
                finally:
                    if tunnel:
                        tunnel.close()
        except Exception as exc:
            if not stopping():
                detail = str(exc)
                if tunnel:
                    detail += "\n" + "\n".join(tunnel.logs)
                key = os.environ.get("OPEN_TERMINAL_API_KEY")
                if key:
                    detail = detail.replace(key, "[redacted]")
                failure.append(detail)
                server.should_exit = True

    supervisor = threading.Thread(target=supervise, name="cloudflared-supervisor")
    def stop_tunnel():
        stopped.set()
        supervisor.join()
    server.stop_tunnel = stop_tunnel
    supervisor.start()
    try:
        server.run()
    except TimeoutError as exc:
        raise click.ClickException("Local server startup timed out") from exc
    finally:
        stop_tunnel()
    if failure:
        raise click.ClickException(failure[0])
    if not server.started:
        raise click.ClickException("Local server failed to start; tunnel was not opened.")
