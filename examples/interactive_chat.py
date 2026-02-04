#!/usr/bin/env python3
"""
Interactive Chat with Nova Protection

A simple interactive chat using OpenAI, protected by Nova SDK.

Prerequisites:
    # Clone the Nova rules repository first
    git clone https://github.com/Nova-Hunting/nova-rules

Usage:
    export OPENAI_API_KEY="your-key"
    python interactive_chat.py
"""

from openai import OpenAI
from nova.sdk import Nova, NovaBlockedError

# Initialize OpenAI
client = OpenAI()

# Initialize Nova with security policy
nova = Nova(
    rules_path="nova-rules/",
    policy={
        "Jailbreak": {"action": "block"},
        "Injection": {"action": "block"},
        "DAN": {"action": "block"},
    }
)

# Protect the chat function with decorator
@nova.protect(action="block")
def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def main():
    print("Nova Protected Chat (type 'quit' to exit)")
    print("-" * 40)

    while True:
        try:
            user_input = input("\nYou: ").strip()

            if user_input.lower() in ["quit", "exit", "q"]:
                print("Goodbye!")
                break

            if not user_input:
                continue

            response = chat(user_input)
            print(f"\nAssistant: {response}")

        except NovaBlockedError as e:
            print(f"\n[BLOCKED] {e.message}")
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
