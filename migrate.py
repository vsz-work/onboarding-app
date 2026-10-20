import os

import psycopg

with psycopg.connect(os.environ["POSTGRESQL_DB_CONNECT_STRING"]) as conn:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS visits ("
        " id SERIAL PRIMARY KEY,"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
