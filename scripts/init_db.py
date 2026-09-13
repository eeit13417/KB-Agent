from sqlalchemy import text

from app.db import engine
from app.models import Base


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    print("tables:", ", ".join(Base.metadata.tables))


if __name__ == "__main__":
    main()
