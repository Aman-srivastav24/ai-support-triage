"""Manual check: what does retrieval actually return for a given question?"""

import sys

# You need three things from your own code:
#   - a database session, because search_chunks talks to Postgres
#   - search_chunks itself
#   - SIMILARITY_FLOOR, so you compare against the real constant, not a
#     number you retyped here (retyped constants drift out of sync)
# TODO 1: write the three imports.
#         Hint: check app/db/session.py and app/services/retrieval.py for
#         the exact names before you guess.
from app.core.config import get_settings






def main() -> None:
    # sys.argv[0] is the script name. Everything after it is what the user
    # typed. The shell already split it on spaces, so argv is a LIST of
    # words — this is the bug you hit in test_llm.py.
    # TODO 2: join everything after argv[0] back into one question string.

    # Fail loudly and early if they ran it with no question. A script that
    # embeds an empty string and returns nonsense is worse than one that
    # refuses to start.
    # TODO 3: if the question is empty, print usage and sys.exit(1).

    print(f"Question: {question}\n")

    # search_chunks needs a live session. Open one, use it, close it in
    # finally — same rule as ingest_document on Day 2: the connection goes
    # back to the pool even if the code between raises.
    db = SessionLocal()
    try:
        # TODO 4: call search_chunks for the top 3 results.
        #         Check its signature — argument order and the name of the
        #         limit/top-k parameter. Do not assume.
        results = ...
    finally:
        db.close()

    # TODO 5: loop over results. For each one print:
    #           - its position (1, 2, 3)
    #           - the similarity score to 4 decimal places
    #           - the first 80 characters of the chunk text, on one line
    #         Watch out: chunk text contains newlines. If you print it raw
    #         the output breaks into multiple lines and becomes unreadable.
    #         Also check what attribute holds the text on RetrievedChunk.

    # The question the floor actually answers is "did anything clear the
    # bar", not "how many" — so this is a boolean over the whole list.
    # TODO 6: print whether ANY result's similarity >= SIMILARITY_FLOOR,
    #         and print the floor value itself so the number is visible.


if __name__ == "__main__":
    main()