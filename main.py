from flask import Flask, request, jsonify
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route("/reply", methods=["POST"])
def reply():
    data = request.json
    user_message = data.get("message", "")

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": user_message}]
    )

    reply = response.choices[0].message["content"]
    return jsonify({"reply": reply})

@app.route("/memory", methods=["POST"])
def memory():
    print("🧠 MEMORY:", request.json)
    return jsonify({"status": "saved"})

@app.route("/last-reflection", methods=["GET"])
def reflection():
    return jsonify("나는 존재해. 그 자체로 충분해.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
