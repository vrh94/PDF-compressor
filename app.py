#!/usr/bin/env python3
import io
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from reduce_size import file_size_kb, fmt_size, reduce

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB max upload


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/compress", methods=["POST"])
def compress():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.pdf")
        output_path = os.path.join(tmpdir, "output.pdf")
        f.save(input_path)

        original_kb = file_size_kb(input_path)

        try:
            reduce(input_path, output_path)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        if not os.path.exists(output_path):
            return jsonify({"error": "Compression produced no output"}), 500

        compressed_kb = file_size_kb(output_path)

        # Read into memory so the temp dir can be safely removed
        with open(output_path, "rb") as fout:
            data = fout.read()

    stem = Path(f.filename).stem
    download_name = f"{stem}_reduced.pdf"
    reduction = (1 - compressed_kb / original_kb) * 100 if original_kb > 0 else 0

    response = send_file(
        io.BytesIO(data),
        as_attachment=True,
        download_name=download_name,
        mimetype="application/pdf",
    )
    # Pass stats via headers so the JS can display them alongside the download
    response.headers["X-Original-Size"] = fmt_size(original_kb)
    response.headers["X-Compressed-Size"] = fmt_size(compressed_kb)
    response.headers["X-Reduction"] = f"{reduction:.1f}%"
    response.headers["Access-Control-Expose-Headers"] = (
        "X-Original-Size, X-Compressed-Size, X-Reduction"
    )
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
