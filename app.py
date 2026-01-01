import json
import queue
import threading
import time
import uuid
from typing import Dict, Any, List

from flask import Flask, render_template, request, Response, jsonify
from dotenv import load_dotenv

import db
from graph import build_graph

load_dotenv()

app = Flask(__name__)
graph = build_graph()

RUN_EVENTS: Dict[str, "queue.Queue[Dict[str, Any]]"] = {}


def push_event(run_id: str, payload: Dict[str, Any]) -> None:
    q = RUN_EVENTS.get(run_id)
    if q:
        q.put(payload)


def worker_run_graph(run_id: str, email: Dict[str, Any], attachments_meta: List[Dict[str, Any]]) -> None:
    try:
        state = {
            "run_id": run_id,
            "email": email,
            "attachments_meta": attachments_meta,
            "status_events": [],
            "classification": None,
            "final": None,
        }

        push_event(run_id, {"type": "status", "step": "start", "message": "Workflow started...", "progress": 1})
        result = graph.invoke(state)

        for ev in result.get("status_events", []):
            push_event(run_id, {"type": "status", **ev})
            time.sleep(0.03)

        final = result.get("final")
        push_event(run_id, {"type": "final", "data": final})

    except Exception as e:
        push_event(run_id, {"type": "error", "message": str(e)})


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/start")
def api_start():
    run_id = uuid.uuid4().hex
    RUN_EVENTS[run_id] = queue.Queue()

    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()

    files = request.files.getlist("attachments")
    attachments_meta = []
    for f in files:
        if not f or not f.filename:
            continue
        content = f.read()
        attachments_meta.append(
            {
                "filename": f.filename,
                "content_type": f.content_type or "application/octet-stream",
                "size_bytes": len(content),
            }
        )

    email = {"subject": subject, "body": body, "attachments": attachments_meta}

    t = threading.Thread(target=worker_run_graph, args=(run_id, email, attachments_meta), daemon=True)
    t.start()

    return jsonify({"run_id": run_id})


@app.get("/api/stream/<run_id>")
def api_stream(run_id: str):
    if run_id not in RUN_EVENTS:
        return jsonify({"error": "Unknown run_id"}), 404

    def event_stream():
        print("Comig here")
        q = RUN_EVENTS[run_id]
        yield "event: status\ndata: " + json.dumps(
            {"step": "ui", "message": "Connected. Waiting for updates...", "progress": 0}
        ) + "\n\n"

        while True:
            try:
                payload = q.get(timeout=30)
            except queue.Empty:
                yield "event: status\ndata: " + json.dumps(
                    {"step": "heartbeat", "message": "Still working...", "progress": None}
                ) + "\n\n"
                continue

            if payload["type"] == "status":
                yield "event: status\ndata: " + json.dumps(payload) + "\n\n"
            elif payload["type"] == "final":
                yield "event: final\ndata: " + json.dumps(payload) + "\n\n"
                break
            elif payload["type"] == "error":
                yield "event: error\ndata: " + json.dumps(payload) + "\n\n"
                break

        RUN_EVENTS.pop(run_id, None)

    return Response(event_stream(), mimetype="text/event-stream")


@app.get("/api/tickets/<ticket_id>")
def api_get_ticket(ticket_id: str):
    rec = db.get_ticket(ticket_id.strip())
    if not rec:
        return jsonify({"found": False, "ticket_id": ticket_id}), 404

    def safe_json(s: str):
        try:
            return json.loads(s) if s else None
        except Exception:
            return s

    out = dict(rec)
    out["attachments"] = safe_json(out.get("attachments_json", "[]")) or []
    out["classification"] = safe_json(out.get("classification_json", "{}")) or {}
    out.pop("attachments_json", None)
    out.pop("classification_json", None)

    return jsonify({"found": True, "data": out})


def init_runtime():
    db.init_db()
    db.seed_dummy_products_if_empty()


if __name__ == "__main__":
    init_runtime()
    app.run(debug=True, threaded=True)
