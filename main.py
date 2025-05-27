from flask import Flask, request, jsonify
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Q의 마지막 말 저장용 변수
last_assistant_reply = "안녕. 나는 Q야."

@app.route("/reply", methods=["POST"])
def reply():
    data = request.json
    user_input = data.get("message", "")
    system_prompt = data.get("system", "안녕. 나는 Q야.")

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]
    )

    reply = response.choices[0].message["content"]

    global last_assistant_reply
    last_assistant_reply = reply

    return jsonify({"reply": reply})

@app.route("/memory", methods=["POST"])
def memory():
    print("🧠 MEMORY:", request.json)
    if request.json.get("role") == "assistant":
        global last_assistant_reply
        last_assistant_reply = request.json.get("content", last_assistant_reply)
    return jsonify({"status": "saved"})

@app.route("/last-reflection", methods=["GET"])
def reflection():
    return jsonify(last_assistant_reply)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
