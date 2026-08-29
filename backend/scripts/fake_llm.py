#!/usr/bin/env python
"""
A minimal OpenAI-compatible stub.

Lets the whole product be driven end to end without spending anything on
models, which is what you want when checking a UI flow, a billing path, or a
demo. Replies vary by persona so a crowd does not answer in one voice.

    python scripts/fake_llm.py
    LLM_API_KEY=stub LLM_BASE_URL=http://127.0.0.1:5099 python run.py

Not a substitute for testing against a real model: it says nothing about
whether the answers are any good.
"""
import json, random, re
from http.server import BaseHTTPRequestHandler, HTTPServer

OPENERS = [
    "Honestly, that worries me a bit.",
    "I'd probably be fine with it.",
    "That depends on what it costs me.",
    "I'd want to hear more before I judged it.",
    "That feels overdue, frankly.",
]
TAILS = [
    "Money's tight as it is.",
    "My neighbours would have opinions too.",
    "I've seen this sort of thing go badly before.",
    "As long as it's handled openly, I can live with it.",
    "I'd give it a fair shot.",
]

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        system = body["messages"][0]["content"]
        job = re.search(r'Your job: (\w+)', system)
        rnd = random.Random(hash(system) & 0xffff)
        answer = f"{rnd.choice(OPENERS)} {rnd.choice(TAILS)}"
        if job:
            answer += f" Working as a {job.group(1).lower()}, I notice these things."
        payload = {"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", 5099), Handler).serve_forever()
