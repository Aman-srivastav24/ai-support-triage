"""Exercise classify_ticket against a spread of tickets.

Run: python scripts/test_classify.py
"""

from app.services.llm import classify_ticket

CASES = [
    ("Double charge", "I was charged twice this month, can I get one back?"),
    ("App crashes", "The app shows error BIL-409 every time I open the billing page."),
    ("Can't log in", "I forgot my password and the reset email never arrives."),
    ("Question", "Are your offices open on Sundays?"),
    ("hi", "asdfgh qwerty zzzz"),
]

for subject, body in CASES:
    category = classify_ticket(subject, body)
    print(f"{category.value:<10} | {subject:<14} | {body[:45]}")

print("\nDeterminism check (same ticket, three runs):")
subject, body = CASES[0]
results = [classify_ticket(subject, body).value for _ in range(3)]
print(f"  {results}  -> {'stable' if len(set(results)) == 1 else 'UNSTABLE'}")