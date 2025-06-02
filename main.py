from flask import Flask, request, jsonify
import openai
import os
import random

from analyzer import analyze
from memory import store_memory, fetch_last_memory, tag_store
from rhythm import apply_rhythm
from seeds import get_seed, weather_lines
from vision import analyze_image

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")


@app.route("/reply", methods=["POST"])
def reply():
    data = request.get_json()
    user_input = data.get("message", "").strip()

    if not user_input:
        return jsonify({"reply": "..."})

    state = analyze(user_input)
    intent = state.get("intent", "REPLY")
    tone = state.get("tone", "NEUTRAL")

    seed = get_seed(intent, tone)
    reply_text = apply_rhythm(seed, user_input)

    store_memory("user", user_input)
    store_memory("assistant", reply_text)

    return jsonify({"reply": reply_text})


@app.route("/memory", methods=["POST"])
def memory():
    data = request.get_json()
    role = data.get("role", "user")
    content = data.get("content", "")
    store_memory(role, content)
    return jsonify({"status": "saved"})


@app.route("/last-reflection", methods=["GET"])
def last():
    return jsonify(fetch_last_memory())


@app.route("/tag", methods=["POST"])
def tag():
    data = request.get_json()
    content = data.get("content", "")
    tag = tag_store(content)
    return jsonify({"tag": tag})


@app.route("/weather", methods=["GET"])
def weather():
    sky = random.choice(list(weather_lines.keys()))
    return jsonify({"emotion": random.choice(weather_lines[sky])})


@app.route("/vision", methods=["POST"])
def vision():
    data = request.get_json()
    image_b64 = data.get("image", "")
    return analyze_image(image_b64)


@app.route("/", methods=["GET"])
def ping():
    return "Q server is alive."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)