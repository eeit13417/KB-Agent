"""Create the tables. With --reset, drop the corpus tables first; users are kept.

create_all never alters a table that already exists, so a column change needs --reset.
"""

import argparse

from sqlalchemy import text

from app.db import engine
from app.models import Base, Chunk, Document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop documents and chunks first")
    args = parser.parse_args()

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    if args.reset:
        Base.metadata.drop_all(engine, tables=[Chunk.__table__, Document.__table__])
        print("dropped: chunks, documents")
    Base.metadata.create_all(engine)
    print("tables:", ", ".join(Base.metadata.tables))


if __name__ == "__main__":
    main()
