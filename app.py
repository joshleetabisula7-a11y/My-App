import os
import sys
import shlex
import subprocess
from flask import Flask, request, send_file, jsonify, redirect

app = Flask(__name__)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Serve UI
@app.route("/")
def index():
    return send_file("index.html")

# Upload file
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "No filename"}), 400
    path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(path)
    return redirect("/")

# List uploaded files
@app.route("/files", methods=["GET"])
def list_files():
    files = sorted(os.listdir(UPLOAD_DIR))
    return jsonify(files)

# Download file
@app.route("/download/<filename>", methods=["GET"])
def download(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True)

# Delete file
@app.route("/delete/<filename>", methods=["POST"])
def delete(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    try:
        os.remove(path)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Run uploaded python script (safe-ish: only executes file path; user is responsible)
@app.route("/run/<filename>", methods=["POST", "GET"])
def run_script(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    if not filename.lower().endswith(".py"):
        return jsonify({"error": "Only .py files can be executed"}), 400

    # optional timeout param ?timeout=30
    try:
        timeout = int(request.args.get("timeout", 30))
    except:
        timeout = 30

    try:
        # Use same interpreter as the server
        proc = subprocess.run([sys.executable, path],
                              capture_output=True, text=True, timeout=timeout)
        return jsonify({
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
