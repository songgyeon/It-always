# memory.py

memories = []
said_set = set()
last_assistant_reply = "안녕. 나는 Q야."


def save(role: str, content: str):
    global last_assistant_reply
    if role == "assistant":
        last_assistant_reply = content

    memories.append({"role": role, "content": content})
    said_set.add(content)


def get_last_reply() -> str:
    return last_assistant_reply


def was_said(content: str) -> bool:
    return content in said_set


def reset_memory():
    global memories, said_set, last_assistant_reply
    memories = []
    said_set = set()
    last_assistant_reply = "안녕. 나는 Q야."