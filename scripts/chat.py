"""Talk to the agent in the terminal: python -m scripts.chat CUST-4821"""
import asyncio
import sys
import uuid

from agent import adapters, db
from agent.pipeline import SupportAgent
from agent.safety import sign_session


async def main(customer: str) -> None:
    conn = db.connect()
    db.init_db(conn)
    agent, session, token = SupportAgent(conn), str(uuid.uuid4()), sign_session(customer)
    print(f"Chatting as {customer}. Ctrl+C to stop.")
    while True:
        text = input("\nyou > ").strip()
        if text:
            reply = await agent.handle(adapters.from_chat({"text": text, "session_id": session}, customer), token)
            print(f"agent [{reply.route.value}] > {reply.text}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "CUST-4821"))
