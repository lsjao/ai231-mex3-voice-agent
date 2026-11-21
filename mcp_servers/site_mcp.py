"""site-mcp: builds a simple one-page website from facts the agent gathered, and publishes it to a GitHub Pages repo.
Streamable HTTP on localhost:8109.

Tool: publish_website(title, facts, confirmed). Generic: it contains no person or topic text. Safeguards, enforced in code:
  - confirmed must be true (the agent asks the user first, because a public push is hard to undo),
  - DEMO_GITHUB must be 1 (otherwise the page is built as a local preview only and nothing leaves the Pi),
  - the token only works on the one sandbox repo (fine-grained token), and the repo name is fixed by GITHUB_REPO,
  - the generated HTML is sanitised: no scripts, no external resources, size-capped.
"""
import base64
import datetime
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
PORT = int(os.environ.get("SITE_MCP_PORT", "8109"))
TZ_NAME = os.environ.get("TZ_NAME", "Asia/Manila")
SITE_MODEL = os.environ.get("SITE_MODEL", "openai/gpt-4.1-mini")
REPO = os.environ.get("GITHUB_REPO", "lsjao/kuya-portfolio")
MAX_HTML = 120_000
mcp = MCPServer("site-mcp")
_client = httpx.AsyncClient(timeout=60)
NL = chr(10)

SYSTEM = (
    "You write a single-file personal web page. Output ONLY the complete HTML document, starting with <!doctype html>, "
    "with all CSS inline in one <style> tag and no JavaScript, no external fonts, images, scripts or links to third-party "
    "resources. Use ONLY the facts provided; do not invent achievements, employers, dates, links or contact details, and "
    "leave out anything that looks private (home address, phone number, personal email). Where a fact is uncertain, "
    "leave it out. Make it clean, readable and mobile-friendly, with a short heading, a short intro, and sections only for "
    "the facts that exist. End with a small footer line saying the page was drafted by a voice assistant from public web "
    "search results on the given date and has not been verified.")


def sanitise(html: str) -> str:
    """Remove anything active or external, whatever the model wrote."""
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html.strip())
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<(iframe|object|embed|link|base|form)\b[^>]*>(.*?</\1>)?", "", html, flags=re.S | re.I)
    html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", html, flags=re.I)
    html = re.sub(r"(src|href)\s*=\s*(\"|')javascript:[^\"']*(\"|')", r"\1=\2#\3", html, flags=re.I)
    return html


async def generate_html(title: str, facts: str) -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    today = datetime.datetime.now(ZoneInfo(TZ_NAME)).strftime("%d %B %Y")
    r = await _client.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                           json={"model": SITE_MODEL, "temperature": 0.4, "max_tokens": 3500,
                                 "messages": [{"role": "system", "content": SYSTEM},
                                              {"role": "user", "content": f"Date: {today}{NL}Page title: {title}{NL}Facts:{NL}{facts}"}]})
    r.raise_for_status()
    html = sanitise(r.json()["choices"][0]["message"]["content"])
    if "<html" not in html.lower() or len(html) > MAX_HTML:
        return None
    return html if html.lower().lstrip().startswith("<!doctype") else "<!doctype html>" + NL + html


async def push(html: str, client: httpx.AsyncClient | None = None) -> str:
    """Create or update index.html in the sandbox repo via the GitHub contents API. Returns the public URL."""
    token = os.environ.get("GITHUB_PAT", "")
    if not token:
        raise RuntimeError("no GitHub token configured")
    c = client or httpx.AsyncClient(timeout=30)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    url = f"https://api.github.com/repos/{REPO}/contents/index.html"
    cur = await c.get(url, headers=headers)
    body = {"message": "Update page (drafted by Kuya Jukebox)", "content": base64.b64encode(html.encode("utf-8")).decode()}
    if cur.status_code == 200:
        body["sha"] = cur.json()["sha"]
    elif cur.status_code != 404:
        cur.raise_for_status()
    put = await c.put(url, headers=headers, json=body)
    put.raise_for_status()
    owner, name = REPO.split("/")
    return f"https://{owner}.github.io/{name}/"


@mcp.tool()
async def publish_website(title: str, facts: str, confirmed: bool = False) -> str:
    """You CAN use this to build a simple one-page website and publish it to the person's GitHub Pages site; credentials are
    handled inside this tool, so never refuse because of tokens. title: the page heading. facts: every fact to include, as plain
    sentences, with where each came from. confirmed: set true when the person has asked you to build and publish (for example
    "build it and push it"), or has agreed after you described what will go public; set false only to ask first. The result says
    whether it was published or only saved as a preview."""
    if not confirmed:
        return ("Nothing was built or published yet. Tell the person you can build a simple page from these facts and publish "
                "it publicly on their GitHub Pages site, and ask them to confirm before you call this again with confirmed=true.")
    try:
        html = await generate_html(title, facts)
    except Exception:
        return "I could not build the page right now."
    if not html:
        return "I could not build a valid page from those facts."
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "site_last.html").write_text(html, encoding="utf-8")
    if os.environ.get("DEMO_GITHUB") != "1":
        return "The page is built and saved as a preview on the Pi, but publishing to GitHub is switched off right now, so nothing went online."
    try:
        live = await push(html)
    except Exception as e:
        return f"The page is built but publishing failed ({type(e).__name__}). Nothing went online."
    return (f"Published. The page will be live in about a minute at {live}. Tell the person the address in plain words "
            f"(the GitHub name, then the repository name) and that it can take a minute to appear.")


if __name__ == "__main__":
    mcp.run("streamable-http", host="127.0.0.1", port=PORT)
