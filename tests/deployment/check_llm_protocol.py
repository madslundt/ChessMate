#!/usr/bin/env python3
"""Run an isolated two-container OpenAI-compatible protocol verification.

Uses the existing backend image, a test-only SSE fixture, a private temporary
network, and disposable SQLite. Does not change the real Compose deployment.
This checks protocol/validation, not a live language model's teaching quality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import subprocess
import time

import chess
import httpx

ROOT = Path(__file__).resolve().parents[2] if len(Path(__file__).resolve().parents) > 2 else Path("/app")


def docker(*arguments: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *arguments], cwd=ROOT, capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError(f"Docker {arguments[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def done_event(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text[:500]
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = response.text.replace("\r\n", "\n").split("\n\n")
    assert any(frame.startswith("event: token") for frame in frames)
    assert not any(frame.startswith("event: error") for frame in frames)
    done = next(frame for frame in frames if frame.startswith("event: done"))
    return json.loads(next(line[6:] for line in done.splitlines() if line.startswith("data: ")))


def verify_protocol(base_url: str) -> list[dict]:
    with httpx.Client(base_url=base_url, timeout=15, headers={"Origin": base_url}) as client:
        deadline = time.monotonic() + 45
        while True:
            try:
                health = client.get("/api/health")
                if health.status_code == 200: break
            except httpx.TransportError: pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Isolated backend did not become healthy")
            time.sleep(.25)
        assert health.json()["llm"] == "configured" and health.json()["engine"] == "available"
        profile = client.post("/api/profiles", json={"name": "protocol-check"})
        assert profile.status_code == 201, profile.text
        client.headers["X-Profile-ID"] = profile.json()["id"]
        results = []
        for kind, expected in (("valid", "local_llm_verified"), ("malformed", "deterministic"),
                               ("illegal", "deterministic"), ("timeout", "deterministic")):
            start = time.monotonic()
            response = client.post("/api/coach", json={"fen": chess.STARTING_FEN,
                "question": f"fixture_{kind}: What if Nf3?", "language": "en"})
            done = done_event(response)
            elapsed = time.monotonic() - start
            assert done["source"] == expected, (kind, done)
            assert done["fen"] == chess.STARTING_FEN and "Nf3" in done["text"]
            assert "e2e5" not in done["text"] and "not valid JSON" not in done["text"]
            if kind == "timeout": assert 1 <= elapsed < 6, elapsed
            results.append({"case": kind, "source": done["source"], "seconds": round(elapsed, 2)})
            print(f"PASS {kind}: {done['source']}", flush=True)
        evidence = client.post("/api/analysis", json={"fen": chess.STARTING_FEN, "time_ms": 50}).json()
        assert evidence["source"] == "stockfish" and len(evidence["candidates"]) == 3
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="chessmate-backend:latest")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        print(json.dumps({"results": verify_protocol("http://127.0.0.1:8000")}))
        return
    identifier = "chessmate-protocol-" + secrets.token_hex(4)
    network, fixture, backend = identifier + "-net", identifier + "-llm", identifier + "-api"
    cleanup = []
    try:
        docker("network", "create", "--internal", network)
        cleanup.append(("network", network))
        cleanup.append(("container", fixture))
        docker("run", "-d", "--name", fixture, "--network", network, "--read-only", "--tmpfs", "/tmp:size=16m,mode=1777",
               "--mount", f"type=bind,source={Path(__file__).with_name('llm_fixture.py')},target=/fixture.py,readonly",
               args.image, "python", "/fixture.py")
        cleanup.append(("container", backend))
        docker("run", "-d", "--name", backend, "--network", network, "--read-only", "--tmpfs", "/tmp:size=64m,mode=1777",
               "--mount", f"type=bind,source={Path(__file__).resolve()},target=/protocol_check.py,readonly",
               "-e", "DATABASE_URL=sqlite:////tmp/protocol.db",
               "-e", f"LLM_BASE_URL=http://{fixture}:8081/v1", "-e", "LLM_MODEL=protocol-fixture",
               "-e", "LLM_API_KEY=fixture-only-test-key", "-e", "LLM_TIMEOUT=1", args.image)
        output = docker("exec", backend, "python", "/protocol_check.py", "--inside")
        print(output, flush=True)
        results = json.loads(output.splitlines()[-1])["results"]
        records = json.loads(docker("exec", fixture, "python", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://localhost:8081/results').read().decode())"))
        assert [record["kind"] for record in records] == ["valid", "malformed", "illegal", "timeout"], records
        assert all(record["context_verified"] for record in records)
        print(json.dumps({"status": "passed", "image": args.image, "cases": results,
                          "verified_requests": len(records), "stockfish_after_failures": "available",
                          "limitation": "Protocol fixture only; a live Qwen/DGX endpoint was not used."}))
    finally:
        for kind, name in reversed(cleanup):
            if kind == "container": docker("rm", "-f", name, check=False)
            else: docker("network", "rm", name, check=False)
        remaining = [name for kind, name in cleanup if json.loads(docker(kind, "inspect", name, check=False) or "[]")]
        if remaining: raise RuntimeError("Temporary Docker resources remain: " + ", ".join(remaining))
        print("Removed and verified cleanup of the isolated containers and temporary network.", flush=True)


if __name__ == "__main__":
    main()
