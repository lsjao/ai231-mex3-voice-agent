#!/usr/bin/env bash
# Switch publishing to GitHub Pages on or off:  bash scripts/demo_github.sh on | off | status
# Edits DEMO_GITHUB in ~/mex3/.env and restarts only site-mcp (:8109) so the change takes effect. Never prints the token.
cd "$HOME/mex3" || exit 1
case "$1" in
  on)  v=1 ;;
  off) v=0 ;;
  status|"") echo "DEMO_GITHUB=$(grep '^DEMO_GITHUB=' .env | cut -d= -f2)  (1 = publishing is live, 0 = preview only)"; exit 0 ;;
  *) echo "usage: demo_github.sh on|off|status"; exit 1 ;;
esac
if grep -q '^DEMO_GITHUB=' .env; then sed -i "s/^DEMO_GITHUB=.*/DEMO_GITHUB=$v/" .env; else echo "DEMO_GITHUB=$v" >> .env; fi
pkill -f "[s]ite_mcp.py"; sleep 1
nohup .venv/bin/python mcp_servers/site_mcp.py >> logs/site.log 2>&1 &
sleep 3
ss -ltn | grep -q "127.0.0.1:8109 " && echo "site-mcp restarted" || echo "WARN: site-mcp not listening yet"
echo "DEMO_GITHUB=$(grep '^DEMO_GITHUB=' .env | cut -d= -f2)"
