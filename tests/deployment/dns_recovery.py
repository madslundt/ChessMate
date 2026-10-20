#!/usr/bin/env python3
"""Verify Docker DNS recovery without touching the main Compose deployment.

Creates isolated chessmate-dns-check-* containers/network using the production
Nginx config. Readdresses a fixture backend and requires recovery without a proxy
restart. Requires a locally available nginx:1.30-alpine image. Exit 1 reproduces
the stale-IP regression with the original static proxy configuration.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def docker(*arguments: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *arguments], capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f"docker {' '.join(arguments)}: {result.stderr.strip()}")
    return result.stdout.strip()


def get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def wait_ready(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if get_json(url) == {"status": "ok"}:
            return True
        time.sleep(.25)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/nginx.conf")
    parser.add_argument("--image", default="nginx:1.30-alpine")
    parser.add_argument("--recovery-timeout", type=float, default=20)
    args = parser.parse_args()
    config = args.config.resolve()
    if not config.is_file():
        parser.error(f"Config not found: {config}")
    prefix = f"chessmate-dns-check-{uuid4().hex[:10]}"
    network, backend, proxy = prefix + "-network", prefix + "-backend", prefix + "-proxy"
    docker("image", "inspect", args.image)
    with tempfile.TemporaryDirectory(prefix=".dns-check-", dir=ROOT / "tests") as directory:
        fixture = Path(directory) / "backend.conf"
        fixture.write_text('''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr;
events { worker_connections 64; }
http {
    access_log off;
    client_body_temp_path /tmp/client_temp;
    proxy_temp_path /tmp/proxy_temp;
    fastcgi_temp_path /tmp/fastcgi_temp;
    uwsgi_temp_path /tmp/uwsgi_temp;
    scgi_temp_path /tmp/scgi_temp;
    server {
        listen 8000;
        default_type application/json;
        location / { return 200 '{"status":"ok"}'; }
    }
}
''')
        network_created = False
        try:
            docker("network", "create", network)
            network_created = True
            details = json.loads(docker("network", "inspect", network))[0]
            subnet = ipaddress.ip_network(details["IPAM"]["Config"][0]["Subnet"])
            old_ip, new_ip, proxy_ip = str(subnet.network_address + 2), str(subnet.network_address + 3), str(subnet.network_address + 4)
            common = ["--detach", "--read-only", "--user", "101:101", "--cap-drop", "ALL",
                      "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:rw,size=32m,mode=1777",
                      "--network", network, "--entrypoint", "nginx"]
            docker("run", *common, "--name", backend, "--ip", old_ip, "--network-alias", "backend",
                   "--mount", f"type=bind,src={fixture},dst=/etc/nginx/nginx.conf,readonly",
                   args.image, "-g", "daemon off;")
            docker("run", *common, "--name", proxy, "--ip", proxy_ip, "--publish", "127.0.0.1::8080",
                   "--mount", f"type=bind,src={config},dst=/etc/nginx/nginx.conf,readonly",
                   args.image, "-g", "daemon off;")
            published = docker("port", proxy, "8080/tcp").splitlines()[0]
            base = "http://" + published
            health = base + "/api/health"
            assert wait_ready(health, 15), "Proxy never reached the original fixture backend"
            before = json.loads(docker("inspect", proxy))[0]
            master_pid = docker("exec", proxy, "cat", "/tmp/nginx.pid")
            print(f"Initial proxy check passed; moving backend from {old_ip} to {new_ip}.", flush=True)
            docker("network", "disconnect", network, backend)
            docker("network", "connect", "--ip", new_ip, "--alias", "backend", network, backend)
            actual = json.loads(docker("inspect", backend))[0]["NetworkSettings"]["Networks"][network]["IPAddress"]
            assert actual == new_ip and actual != old_ip, "Fixture backend IP did not actually change"
            started = time.monotonic()
            assert wait_ready(health, args.recovery_timeout), (
                f"Proxy did not recover within {args.recovery_timeout}s after backend changed IP; "
                "Nginx is still using its startup DNS result"
            )
            for path in ("/docs", "/openapi.json"):
                assert get_json(base + path) == {"status": "ok"}, f"{path} did not use the recovered upstream"
            after = json.loads(docker("inspect", proxy))[0]
            assert before["Id"] == after["Id"] and before["State"]["StartedAt"] == after["State"]["StartedAt"]
            assert master_pid == docker("exec", proxy, "cat", "/tmp/nginx.pid"), "Nginx master restarted"
            print(f"DNS recovery passed in {time.monotonic() - started:.2f}s; API/docs/OpenAPI recovered without restarting Nginx.")
        except Exception:
            print(docker("logs", proxy, check=False)[-3000:])
            raise
        finally:
            docker("rm", "--force", proxy, backend, check=False)
            if network_created:
                docker("network", "rm", network, check=False)
    print("Removed only this check's isolated containers, network, and temporary config.")


if __name__ == "__main__":
    main()
