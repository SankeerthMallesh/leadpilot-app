"""Measure Ollama speed: time to first token (cold and warm) and tokens per second.

Usage:  python scripts/ollama_bench.py [--model llama3.1:8b] [--url http://127.0.0.1:11434]
"""
import argparse
import json
import time

import httpx

PROMPT = "List five practical tips for writing a short, honest B2B cold email."


def run(client: httpx.Client, url: str, model: str, keep_alive: str) -> dict:
    body = {"model": model, "stream": True, "keep_alive": keep_alive,
            "messages": [{"role": "user", "content": PROMPT}], "options": {"num_predict": 200, "num_ctx": 4096}}
    t0, first, final = time.monotonic(), None, {}
    with client.stream("POST", f"{url}/api/chat", json=body) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("message", {}).get("content") and first is None:
                first = (time.monotonic() - t0) * 1000
            if event.get("done"):
                final = event
    tps = final.get("eval_count", 0) / (final.get("eval_duration", 1) / 1e9)
    return {"first_token_ms": round(first or 0), "tokens_per_second": round(tps, 1),
            "load_ms": round(final.get("load_duration", 0) / 1e6)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--url", default="http://127.0.0.1:11434")
    ap.add_argument("--keep-alive", default="30m")
    a = ap.parse_args()
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=5.0)) as c:
        print("run 1 (may include a cold model load):", run(c, a.url, a.model, a.keep_alive))
        print("run 2 (warm):                          ", run(c, a.url, a.model, a.keep_alive))
        print("run 3 (warm):                          ", run(c, a.url, a.model, a.keep_alive))


if __name__ == "__main__":
    main()
