import dotenv
import psycopg
from pypgstac.db import PgstacDB

env_file = "stac/env/.env_production"

dotenv.load_dotenv(env_file)


def main():
    db = PgstacDB()

    confirmation = input(
        f"Are you sure you want to delete all STAC data in {env_file}? (y/N): "
    )
    if confirmation.lower() == "y":
        print("Deleting all STAC items")
        try:
            db.query_one("DELETE FROM pgstac.items")
        except psycopg.ProgrammingError as e:
            print(e)
        print("Successfully deleted all STAC items")
        print("Deleting all STAC collections")
        try:
            db.query_one("DELETE FROM pgstac.collections")
        except psycopg.ProgrammingError as e:
            print(e)
        print("Successfully deleted all STAC collections")
    else:
        print("Operation cancelled")


if __name__ == "__main__":
    main()
