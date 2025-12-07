from flask import Flask, request, send_file, jsonify
import os

app = Flask(__name__)

UPLOAD_DIR = "uploads"

# create uploads folder if not exist
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)


@app.route("/")
def home():
    # serve index.html file
    return send_file("index.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    save_path = os.path.join(UPLOAD_DIR, file.filename)
    file.save(save_path)

    return jsonify({"message": "Uploaded!", "filename": file.filename}), 200


@app.route("/files", methods=["GET"])
def list_files():
    files = os.listdir(UPLOAD_DIR)
    return jsonify(files)


@app.route("/open/<filename>", methods=["GET"])
def open_file(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    return send_file(path)


@app.route("/search", methods=["POST"])
def search_keyword():
    data = request.get_json()
    filename = data.get("filename")
    keyword = data.get("keyword")

    if not filename or not keyword:
        return jsonify({"error": "Missing data"}), 400

    path = os.path.join(UPLOAD_DIR, filename)

    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    results = []
    with open(path, "r", encoding="utf8", errors="ignore") as f:
        for line in f.readlines():
            if keyword.lower() in line.lower():
                results.append(line.strip())

    return jsonify(results)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
