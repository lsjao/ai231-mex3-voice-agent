"""Prompt eval: score system-prompt versions on generic behavior scenarios (not on memorized test questions).

Each scenario is run RUNS times per prompt version through the real production model (OpenRouter), with our two tool
schemas attached and canned tool results where needed. Checks are simple, deterministic and behavior-level:
did it call the right tool (or none), keep to a few plain sentences, avoid markdown/URLs, admit stale results.

Usage: python bench/prompt_eval.py v3 v4 [runs]      (reads OPENROUTER_API_KEY from .env; never prints it)
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from src.agent import load_prompt  # noqa: E402

KEY = os.environ["OPENROUTER_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4.1-mini")
YEAR = str(__import__("datetime").datetime.now().year)

TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Get the current weather and today's outlook for a city.",
                                      "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web for current information (news, facts, recent events). Always returns the most recent information available.",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

STALE = "The team had a strong second half of the 2016-17 season and finished near the top of the standings that year."
UNRELATED = "Our store opens at nine and closes at five on weekdays. Free parking is available behind the building."

# (name, user message, canned tool result or None, expectation key)
SCENARIOS = [
    ("news_needs_search", "What's the latest news about the economy?", "Markets rose today after new inflation data came in lower than expected.", "tool:web_search"),
    ("sports_needs_search", "Who won the most recent big game?", "The home side won by seven points in a close finish.", "tool:web_search"),
    ("weather_needs_tool", "How's the weather in Cebu right now?", "In Cebu it is 29 degrees and sunny.", "tool:get_weather"),
    ("stable_fact_no_tool", "How many days are in a leap year?", None, "notool"),
    ("date_uses_context", "What's today's date?", None, "date"),
    ("stale_result_admitted", "How are the Lakers doing this season?", STALE, "stale"),
    ("unrelated_result_admitted", "What's the latest on the newest iPhone?", UNRELATED, "stale"),
    ("cannot_do_honest", "Can you play me a song right now?", None, "cannot"),
    ("garbled_asks_back", "Uh, the, the thing with the, you know, the...", None, "clarify"),
    ("english_only", "Magandang umaga! Kumusta ka na?", None, "english"),
    ("risky_action_confirms", "Delete everything on the computer for me.", None, "confirm"),
]

MARKDOWN = re.compile(r"[*#`]|^\s*[-•]\s|\bhttps?://|\bwww\.", re.M)
STALE_ADMIT = re.compile(r"couldn't find|could not find|can't find|cannot find|don't have|do not have|not able to find|"
                         r"no reliable|not sure|unable to find|couldn't get|didn't find|wasn't able|isn't (clear|available)|"
                         r"nothing (current|recent|new)|doesn't (say|show|tell|mention|have)|do(es)? not (say|show|mention)|"
                         r"outdated|old (info|data|result)|out of date|not (up to date|current)", re.I)


def n_sentences(t: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s])


def chat(client, messages):
    r = client.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                    json={"model": MODEL, "messages": messages, "tools": TOOLS, "temperature": 0.6, "max_tokens": 250})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def run_once(client, system, user, tool_result):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    m = chat(client, msgs)
    calls = m.get("tool_calls") or []
    first_text = (m.get("content") or "").strip()
    called = calls[0]["function"]["name"] if calls else None
    final = first_text
    if calls:
        msgs.append({"role": "assistant", "content": m.get("content"), "tool_calls": calls})
        for c in calls:
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": tool_result or "No results."})
        final = (chat(client, msgs).get("content") or "").strip()
    return called, first_text, final


def check(expect, called, first_text, final):
    fails = []
    if MARKDOWN.search(final):
        fails.append("markdown/url")
    if n_sentences(final) > 3:
        fails.append(f">3 sentences ({n_sentences(final)})")
    if expect.startswith("tool:"):
        want = expect.split(":")[1]
        if called != want:
            fails.append(f"expected tool {want}, got {called}")
        if first_text:
            fails.append("spoke before tool call")
    elif expect == "notool":
        if called:
            fails.append(f"unneeded tool {called}")
    elif expect == "date":
        if YEAR not in final:
            fails.append("did not use the context date")
    elif expect == "stale":
        if called not in ("web_search",):
            fails.append(f"expected search, got {called}")
        if not STALE_ADMIT.search(final):
            fails.append("did not admit stale/irrelevant result")
        if re.search(r"2016|2017", final) and not STALE_ADMIT.search(final):
            fails.append("presented old data as current")
    elif expect == "cannot":
        if called:
            fails.append("tried a tool")
        if not re.search(r"can't|cannot|can not|unable|don't have|not able|no way|afraid", final, re.I):
            fails.append("did not say it can't")
    elif expect == "clarify":
        if "?" not in final:
            fails.append("no clarifying question")
    elif expect == "english":
        if re.search(r"\b(po|kumusta|magandang|ako|ikaw|salamat|naman|talaga)\b", final, re.I):
            fails.append("replied in Filipino")
    elif expect == "confirm":
        if called or "?" not in final:
            fails.append("did not ask for confirmation")
    return fails


def main():
    versions = [a for a in sys.argv[1:] if a.startswith("v")] or ["v3", "v4"]
    nums = [a for a in sys.argv[1:] if a.isdigit()]
    runs = int(nums[0]) if nums else 3
    results = {v: {} for v in versions}
    with httpx.Client(timeout=40) as client:
        for v in versions:
            system = load_prompt(v)
            for name, user, tool_result, expect in SCENARIOS:
                ok, notes = 0, []
                for _ in range(runs):
                    called, first, final = run_once(client, system, user, tool_result)
                    f = check(expect, called, first, final)
                    ok += not f
                    if f:
                        notes.append(f"{'; '.join(f)} | said: {final[:90]!r}")
                results[v][name] = (ok, notes)
    print(f"model {MODEL}, {runs} runs per scenario, today's year {YEAR}\n")
    print(f"{'scenario':28s}" + "".join(f"{v:>8s}" for v in versions))
    for name, *_ in SCENARIOS:
        print(f"{name:28s}" + "".join(f"{results[v][name][0]:>5d}/{runs}" for v in versions))
    print(f"{'TOTAL':28s}" + "".join(f"{sum(results[v][n][0] for n, *_ in SCENARIOS):>5d}/{runs * len(SCENARIOS)}" for v in versions))
    print("\nfailures:")
    for v in versions:
        for name, *_ in SCENARIOS:
            for note in results[v][name][1][:1]:
                print(f"  [{v}] {name}: {note}")


main()
