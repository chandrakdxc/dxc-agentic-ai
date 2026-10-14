"""lambda_function.py  --  the AskIT MCP server as an AWS Lambda function (no libraries needed, pure Python).

WHY NO FASTMCP HERE?  MCP is a PROTOCOL: JSON messages over HTTP. This ~120-line file answers those messages by hand,
so you can SEE how little a remote MCP server really is. The 4 tools are the same askit_core/tools.py functions.
(In production you would use a framework, or let AgentCore Gateway do all of this for you: Day 12.)

HOW IT IS CALLED  Lambda Function URL (HTTPS) -> this handler -> JSON answer.
SETTINGS (Lambda > Configuration > Environment variables)
  ASKIT_KEY    your user name, e.g. user101. Callers must send it in the header  x-askit-key  (no key = anyone can call!)
  ASKIT_DELAY  optional, seconds get_ticket waits (used in the incident: slow system)
"""
import base64
import json
import os
import time

from askit_core import tools as T

SERVER = {"name": "AskIT Tools (AWS Lambda)", "version": "1.0"}
MODERN = "2026-07-28"                                   # newest MCP version: stateless, no handshake
CLASSIC = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]   # older clients (handshake style)
COLD = [True]                                           # True only for the first request after a deploy (a "cold start")

TOOLS = [{"name": s["toolSpec"]["name"], "description": s["toolSpec"]["description"],
          "inputSchema": s["toolSpec"]["inputSchema"]["json"]} for s in T.TOOL_SPECS]


def _call_tool(name, args):
    fn = T.TOOLS.get(name)
    if fn is None:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    if name == "get_ticket" and float(os.getenv("ASKIT_DELAY", "0") or 0):
        time.sleep(float(os.environ["ASKIT_DELAY"]))     # the incident: a slow ticket system
    try:
        result = fn(**(args or {}))
    except TypeError as e:
        return {"content": [{"type": "text", "text": f"Bad arguments: {e}"}], "isError": True}
    except Exception as e:                               # noqa: BLE001
        return {"content": [{"type": "text", "text": f"Tool failed: {e}"}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}],
            "structuredContent": result, "isError": False}


def _handle(msg):
    """One JSON-RPC message in, one result (dict) out. Returns None for notifications (no answer wanted)."""
    method, params, mid = msg.get("method", ""), msg.get("params") or {}, msg.get("id")
    meta = {"io.modelcontextprotocol/serverInfo": SERVER}
    if mid is None:                                      # a notification, e.g. notifications/initialized
        return None
    if method == "server/discover":                      # modern clients ask "who are you?" with this
        res = {"_meta": meta, "resultType": "complete", "ttlMs": 0, "cacheScope": "private", "supportedVersions": [MODERN],
               "capabilities": {"tools": {"listChanged": False}},
               "instructions": "Orbit Corp IT helpdesk tools (running on AWS Lambda)."}
    elif method == "initialize":                         # classic clients (handshake style)
        asked = params.get("protocolVersion", CLASSIC[0])
        res = {"protocolVersion": asked if asked in CLASSIC else CLASSIC[0], "serverInfo": SERVER,
               "capabilities": {"tools": {"listChanged": False}}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private", "tools": TOOLS}
    elif method == "tools/call":
        res = _call_tool(params.get("name", ""), params.get("arguments"))
        res.update({"resultType": "complete", "_meta": meta})
    elif method in ("resources/list", "resources/templates/list", "prompts/list"):
        key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates", "prompts/list": "prompts"}[method]
        res = {"resultType": "complete", "ttlMs": 0, "cacheScope": "private", key: []}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def _reply(code, body=None):
    return {"statusCode": code, "headers": {"content-type": "application/json"},
            "body": json.dumps(body) if body is not None else ""}


def lambda_handler(event, context):
    t0 = time.time()
    cold, COLD[0] = COLD[0], False
    http = (event.get("requestContext") or {}).get("http") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    want = os.getenv("ASKIT_KEY", "")
    if want and headers.get("x-askit-key") != want:
        print(json.dumps({"event": "denied", "reason": "missing or wrong x-askit-key header"}))
        return _reply(401, {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized: send header x-askit-key"}})
    if http.get("method", "POST") != "POST":
        return {"statusCode": 405, "headers": {"allow": "POST"}, "body": ""}
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    try:
        msg = json.loads(body)
    except ValueError:
        return _reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    out = _handle(msg)
    tool = (msg.get("params") or {}).get("name", "") if msg.get("method") == "tools/call" else ""
    print(json.dumps({"event": "mcp", "method": msg.get("method"), "tool": tool, "cold_start": cold,
                      "ms": round((time.time() - t0) * 1000), "warn": "" if want else "ASKIT_KEY not set: anyone can call me"}))
    return _reply(202) if out is None else _reply(200, out)
