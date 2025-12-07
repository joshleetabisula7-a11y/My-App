from flask import Flask, send_from_directory, request, jsonify, redirect
import subprocess, os

app = Flask(__name__, static_folder="static")
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return send_from_directory("static", "index.html")

# Upload file
@app.route("/upload", methods=["POST"])
def upload_file():
    file = request.files.get("file")
    if not file:
        return "No file uploaded"

    save_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(save_path)
    return redirect("/")

# List uploaded files
@app.route("/list")
def list_files():
    files = os.listdir(UPLOAD_FOLDER)
    return jsonify(files)

# Run python file
@app.route("/run/<filename>")
def run_python(filename):
    full = os.path.join(UPLOAD_FOLDER, filename)
    if not filename.endswith(".py"):
        return "<h3>❌ Only .py files can be executed</h3>"
    if not os.path.exists(full):
        return "File not found"

    out = subprocess.run(["python3", full], capture_output=True, text=True)
    return f"<pre>{out.stdout}\n{out.stderr}</pre>"

# Download txt
@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)