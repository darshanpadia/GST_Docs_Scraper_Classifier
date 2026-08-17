"""Local web dashboard for operating and inspecting the agent.

A thin read/trigger layer over the same gst_agent.db and gst_agent.pipeline
the CLI uses -- nothing in the core pipeline depends on this module, and it
changes no behavior of its own; it only calls the same functions `--once`
and `--retry-failed` already call. Purely additive, for a reviewer/operator
who'd rather click buttons and browse tables than run CLI commands.

Local-use only: binds to 127.0.0.1 (see main()), not 0.0.0.0 -- this is an
operator console for whoever is sitting at this machine, not a public
service, and intentionally has no authentication.
"""
from __future__ import annotations

import os

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from gst_agent import db, pipeline
from gst_agent.config import ensure_directories, settings
from gst_agent.db import STATUS_DISCOVERED, STATUS_DONE, STATUS_FAILED
from gst_agent.logging_setup import configure_logging

PAGE_SIZE = 50
_STATUS_CHOICES = [STATUS_DISCOVERED, "downloaded", "extracted", "classified", STATUS_DONE, STATUS_FAILED]

app = Flask(__name__)
# Only signs the flash-message cookie for this local session -- there is no
# real authentication here, so a persistent secret buys nothing.
app.secret_key = os.urandom(32)


@app.route("/")
def dashboard():
    with db.open_db(settings.db_path) as conn:
        stats = db.get_stats(conn)
        runs = db.get_recent_runs(conn, limit=10)
    return render_template("dashboard.html", stats=stats, runs=runs)


@app.route("/run", methods=["POST"])
def run_now():
    with db.open_db(settings.db_path) as conn:
        try:
            result = pipeline.run_once(conn)
            flash(
                f"Run #{result['run_id']} complete: "
                f"{result['new_documents_downloaded']} new document(s) downloaded.",
                "success",
            )
        except Exception as exc:
            flash(f"Run failed: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.route("/retry-failed", methods=["POST"])
def retry_failed():
    with db.open_db(settings.db_path) as conn:
        try:
            result = pipeline.retry_failed(conn)
            flash(f"Retried {result['retried']} failed document(s).", "success")
        except Exception as exc:
            flash(f"Retry failed: {exc}", "error")
    return redirect(url_for("dashboard"))


@app.route("/documents")
def documents():
    category = request.args.get("category") or None
    status = request.args.get("status") or None
    page = max(1, request.args.get("page", 1, type=int))
    offset = (page - 1) * PAGE_SIZE

    with db.open_db(settings.db_path) as conn:
        rows, total = db.get_documents(
            conn, category=category, status=status, limit=PAGE_SIZE, offset=offset
        )
        active_categories = pipeline.get_active_categories(conn)

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return render_template(
        "documents.html",
        documents=rows,
        total=total,
        page=page,
        total_pages=total_pages,
        category=category,
        status=status,
        categories=active_categories,
        statuses=_STATUS_CHOICES,
    )


@app.route("/documents/<int:doc_id>/file")
def document_file(doc_id: int):
    with db.open_db(settings.db_path) as conn:
        row = db.get_document(conn, doc_id)
    if row is None or not row["local_path"]:
        abort(404)
    path = pipeline.to_absolute_download_path(row["local_path"])
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="application/pdf")


@app.route("/logs")
def logs():
    lines_count = request.args.get("lines", 200, type=int)
    log_path = settings.log_dir / "gst_agent.log"
    lines = (
        log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines_count:]
        if log_path.is_file()
        else []
    )
    return render_template("logs.html", lines=lines, lines_count=lines_count)


def main() -> None:
    ensure_directories()
    configure_logging(settings.log_dir)
    # Defaults to loopback-only, since this is a single-user local operator
    # console with no authentication -- it should not be reachable from the
    # network by default. The Dockerfile overrides WEB_UI_HOST to 0.0.0.0,
    # which is standard/expected there: the container's own network
    # namespace is already the isolation boundary, and Docker's `-p` port
    # publishing forwards to the container's external interface, not its
    # loopback -- a container process bound to 127.0.0.1 is unreachable via
    # `-p` no matter what, so it must bind wider inside the container.
    host = os.environ.get("WEB_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_UI_PORT", "5000"))
    # threaded=True matters here: "Run now" can take several minutes (it's a
    # real scrape with rate limiting), and without this the single-threaded
    # dev server can't serve *any* other page -- including Logs -- until
    # that request finishes, making a long run look hung with no way to
    # check on it.
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
