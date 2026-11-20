"""Pre-demo check: are the API keys valid, and how much credit/quota is left? Read-only. Never prints a key.
Usage: python bench/check_keys.py   (reads .env in the project root)"""
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get(url, key, label, fmt):
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {key}" if label != "Deepgram" else f"Token {key}"},
                      timeout=15)
        print(f"{label:11s} HTTP {r.status_code}  {fmt(r.json()) if r.status_code == 200 else r.text[:120]}")
        return r
    except Exception as e:
        print(f"{label:11s} ERROR {type(e).__name__}: {e}")


def main():
    for name in ("DEEPGRAM_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY"):
        print(f"{name}: {'set' if os.environ.get(name) else 'MISSING'}")
    key = os.environ.get("OPENROUTER_API_KEY", "")
    get("https://openrouter.ai/api/v1/key", key, "OpenRouter",
        lambda j: f"usage ${j['data'].get('usage', 0):.3f}, key limit {j['data'].get('limit')}, "
                  f"remaining {j['data'].get('limit_remaining')}")
    get("https://openrouter.ai/api/v1/credits", key, "OR credits",
        lambda j: f"purchased ${j['data'].get('total_credits', 0):.2f}, used ${j['data'].get('total_usage', 0):.2f}")
    dg = os.environ.get("DEEPGRAM_API_KEY", "")
    r = get("https://api.deepgram.com/v1/projects", dg, "Deepgram",
            lambda j: f"{len(j.get('projects', []))} project(s)")
    if r is not None and r.status_code == 200 and r.json().get("projects"):
        pid = r.json()["projects"][0]["project_id"]
        get(f"https://api.deepgram.com/v1/projects/{pid}/balances", dg, "DG balance",
            lambda j: ", ".join(f"{b.get('amount')} {b.get('units')}" for b in j.get("balances", [])) or "no balances listed")
    tv = os.environ.get("TAVILY_API_KEY", "")
    get("https://api.tavily.com/usage", tv, "Tavily",
        lambda j: f"account {j.get('account', {})}")


main()
