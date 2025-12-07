import os
import time
import signal
import threading
import subprocess
from collections import deque
from flask import Flask, request, send_from_directory, jsonify, redirect, Response

# Configuration
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

LOG_MAX_CHARS = 20000    # keep last ~ chars in memory
LOG_DEQUE = deque()      # in-memory log lines
LOG_LOCK = threading.Lock()

PROC_LOCK = threading.Lock()
PROC_META = {
    "running": False,
    "pid": None,
    "filename": None,
    "started_at": None
}
PROC = None  # subprocess.Popen object

START_TIME = time.time()

app = Flask(__name__, static_folder="static", static_url_path="/static")


# ---------------- utilities ----------------
def append_log_line(line: str):
    """Append a line to the in-memory log buffer and trim by char count."""
    with LOG_LOCK:
        LOG_DEQUE.append(line.rstrip("\n"))
        # trim
        total = sum(len(s) + 1 for s in LOG_DEQUE)
        while total > LOG_MAX_CHARS and LOG_DEQUE:
            removed = LOG_DEQUE.popleft()
            total = sum(len(s) + 1 for s in LOG_DEQUE)


def tail_logs_text():
    with LOG_LOCK:
        return "\n".join(LOG_DEQUE)


def log_path_for(filename):
    safe = os.path.basename(filename)
    return os.path.join(UPLOAD_DIR, f"{safe}.log")


def reader_thread(proc, filename):
    """Read process stdout line-by-line and append to log buffer + file."""
    lp = log_path_for(filename)
    try:
        with open(lp, "a+", encoding="utf8", errors="ignore") as lf:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                lf.write(line)
                lf.flush()
                append_log_line(line)
    except Exception as e:
        append_log_line(f"[reader error] {e}")


def is_proc_running():
    global PROC
    if PROC is None:
        return False
    return PROC.poll() is None


# ---------------- routes ----------------
@app.route("/")
def index():
    # serve the separated static page
    return send_from_directory("static", "index.html")


@app.route("/api/files", methods=["GET"])
def list_files():
    files = sorted(os.listdir(UPLOAD_DIR))
    return jsonify({"files": files})


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No filename"}), 400
    # enforce .py uploads only for scripts; still allow other files (like requirements)
    filename = os.path.basename(f.filename)
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)
    # append a small log notice that a file was uploaded
    append_log_line(f"[uploaded] {filename}")
    return jsonify({"ok": True, "filename": filename})


@app.route("/api/download/<path:filename>", methods=["GET"])
def download(filename):
    safe = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(UPLOAD_DIR, safe, as_attachment=True)


@app.route("/api/delete/<path:filename>", methods=["POST"])
def delete(filename):
    safe = os.path.basename(filename)
    # don't allow deleting a running script
    with PROC_LOCK:
        if PROC_META["running"] and PROC_META["filename"] == safe:
            return jsonify({"error": "Stop the running script first"}), 400
        path = os.path.join(UPLOAD_DIR, safe)
        if not os.path.exists(path):
            return jsonify({"error": "Not found"}), 404
        try:
            os.remove(path)
            # remove log file if exists
            lp = log_path_for(safe)
            try:
                if os.path.exists(lp):
                    os.remove(lp)
            except: pass
            append_log_line(f"[deleted] {safe}")
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


@app.route("/api/start", methods=["POST"])
def start_script():
    global PROC, PROC_META
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"error": "filename required in JSON body"}), 400
    safe = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe)
    if not os.path.exists(path):
        return jsonify({"error": "file not found"}), 404
    if not safe.lower().endswith(".py"):
        return jsonify({"error": "only .py files can be started"}), 400

    with PROC_LOCK:
        if PROC_META["running"] and is_proc_running():
            return jsonify({"error": "another script already running", "running": PROC_META}), 400
        # Clear in-memory logs and append starting notice
        with LOG_LOCK:
            LOG_DEQUE.clear()
        append_log_line(f"[starting] {safe}")
        try:
            # open process with new process group (so children can be killed)
            PROC = subprocess.Popen(
                [subprocess.sys.executable, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
            PROC_META = {
                "running": True,
                "pid": PROC.pid,
                "filename": safe,
                "started_at": time.time()
            }
            # start reader thread
            t = threading.Thread(target=reader_thread, args=(PROC, safe), daemon=True)
            t.start()
            return jsonify({"ok": True, "pid": PROC.pid})
        except Exception as e:
            append_log_line(f"[start error] {e}")
            return jsonify({"error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def stop_script():
    global PROC, PROC_META
    with PROC_LOCK:
        if not PROC_META["running"] or PROC is None:
            return jsonify({"error": "no script running"}), 400
        try:
            pid = PROC.pid
            pg = os.getpgid(pid)
            os.killpg(pg, signal.SIGTERM)
            time.sleep(0.5)
            if PROC.poll() is None:
                os.killpg(pg, signal.SIGKILL)
            append_log_line(f"[stopped] pid {pid}")
        except Exception as e:
            append_log_line(f"[stop error] {e}")
            return jsonify({"error": str(e)}), 500
        finally:
            PROC = None
            PROC_META = {"running": False, "pid": None, "filename": None, "started_at": None}
        return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def status():
    uptime_seconds = int(time.time() - START_TIME)
    service_uptime = {
        "seconds": uptime_seconds,
        "display": f"{uptime_seconds//3600}h {(uptime_seconds%3600)//60}m {uptime_seconds%60}s"
    }
    running = PROC_META["running"] and is_proc_running()
    script_runtime = None
    if running and PROC_META.get("started_at"):
        sec = int(time.time() - PROC_META["started_at"])
        script_runtime = {"seconds": sec, "display": f"{sec//3600}h {(sec%3600)//60}m {sec%60}s"}
    return jsonify({
        "service_uptime": service_uptime,
        "script_running": running,
        "script_meta": PROC_META,
        "script_runtime": script_runtime
    })


@app.route("/api/logs", methods=["GET"])
def logs():
    # return combined memory buffer and tail of disk log if exists
    lines = tail_logs_text()
    # also append the tail of disk file for running script (last ~50KB)
    if PROC_META.get("filename"):
        lp = log_path_for(PROC_META["filename"])
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf8", errors="ignore") as f:
                    data = f.read()
                    # return last ~10000 chars of file + memory buffer
                    tail = data[-10000:]
                    if tail:
                        # put disk tail after memory buffer for completeness
                        lines = (lines + "\n\n" + tail) if lines else tail
            except:
                pass
    return Response(lines or "[no logs yet]", mimetype="text/plain")


# ---------------- run ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # recommended on Render: run via gunicorn: `gunicorn app:app --bind 0.0.0.0:$PORT`
    app.run(host="0.0.0.0", port=port)
# Install requirements from an uploaded requirements file
@app.route("/install_requirements", methods=["POST"])
def install_requirements():
    # choose filename from JSON or form; default to 'requirements.txt'
    data = request.get_json(silent=True) or {}
    filename = data.get("filename") or request.form.get("filename") or "requirements.txt"
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "requirements file not found", "filename": filename}), 404

    try:
        # Install using the running Python interpreter
        cmd = [sys.executable, "-m", "pip", "install", "-r", path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return jsonify({
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "pip install timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
