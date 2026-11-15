#!/usr/bin/env python3
"""Local kanban for PortShift. Reads GitHub issues, PRs and board posts via `gh`
and serves a self-refreshing board. Stdlib only.

    python3 tools/kanban/kanban.py            # http://localhost:8765
    python3 tools/kanban/kanban.py --port 9000 --interval 45
"""
import argparse, json, subprocess, threading, time, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_ISSUE = os.environ.get("BOARD_ISSUE", "1")
STATE = {"data": None, "error": None, "fetched_at": 0}
LOCK = threading.Lock()


def gh(*args):
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "gh failed")
    return json.loads(out.stdout or "null")


def build():
    issues = gh("issue", "list", "--state", "all", "--limit", "200", "--json",
                "number,title,state,assignees,labels,updatedAt,url,createdAt")
    prs = gh("pr", "list", "--state", "all", "--limit", "100", "--json",
             "number,title,state,author,headRefName,updatedAt,url,isDraft,"
             "reviewDecision,closingIssuesReferences,mergedAt")
    comments = gh("issue", "view", BOARD_ISSUE, "--json", "comments")["comments"]

    prs_by_issue = {}
    for p in prs:
        refs = [r["number"] for r in p.get("closingIssuesReferences") or []]
        head = p["headRefName"].split("-", 1)[0]
        if not refs and head.isdigit():
            refs = [int(head)]
        p["issues"] = refs
        for n in refs:
            prs_by_issue.setdefault(n, []).append(p)

    cards, linked = [], set()
    for i in issues:
        if str(i["number"]) == BOARD_ISSUE:
            continue
        mine = prs_by_issue.get(i["number"], [])
        open_prs = [p for p in mine if p["state"] == "OPEN"]
        if i["state"] == "CLOSED":
            col = "done"
        elif open_prs:
            col = "review"
        elif i["assignees"]:
            col = "progress"
        else:
            col = "backlog"
        for p in mine:
            linked.add(p["number"])
        cards.append({
            "kind": "issue", "number": i["number"], "title": i["title"], "col": col,
            "url": i["url"], "updatedAt": i["updatedAt"],
            "people": [a["login"] for a in i["assignees"]],
            "prs": [{"number": p["number"], "state": p["state"], "url": p["url"],
                     "draft": p["isDraft"]} for p in mine],
        })
    for p in prs:  # PRs that close no known issue still deserve a card
        if p["number"] in linked:
            continue
        col = "done" if p["state"] in ("MERGED", "CLOSED") else "review"
        cards.append({
            "kind": "pr", "number": p["number"], "title": p["title"], "col": col,
            "url": p["url"], "updatedAt": p["updatedAt"], "people": [p["author"]["login"]],
            "prs": [{"number": p["number"], "state": p["state"], "url": p["url"],
                     "draft": p["isDraft"]}],
        })
    cards.sort(key=lambda c: c["updatedAt"], reverse=True)

    posts = [{"author": c["author"]["login"], "createdAt": c["createdAt"],
              "body": c["body"][:600]} for c in comments[-25:]][::-1]
    return {"cards": cards, "posts": posts}


def refresher(interval):
    while True:
        try:
            data = build()
            with LOCK:
                STATE.update(data=data, error=None, fetched_at=time.time())
        except Exception as e:  # keep serving the last good snapshot
            with LOCK:
                STATE["error"] = str(e)
        time.sleep(interval)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/data"):
            with LOCK:
                body = json.dumps({**(STATE["data"] or {"cards": [], "posts": []}),
                                   "error": STATE["error"],
                                   "fetched_at": STATE["fetched_at"],
                                   "interval": self.server.interval}).encode()
            ctype = "application/json"
        else:
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--interval", type=int, default=60, help="seconds between GitHub refreshes")
    a = ap.parse_args()
    threading.Thread(target=refresher, args=(a.interval,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    srv.interval = a.interval
    print(f"PortShift kanban on http://localhost:{a.port} (refresh every {a.interval}s)")
    srv.serve_forever()
