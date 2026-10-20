import os

import flask
import psycopg

app = flask.Flask(__name__)


def get_conn():
    return psycopg.connect(os.environ["POSTGRESQL_DB_CONNECT_STRING"])


@app.route("/")
def index():
    with get_conn() as conn:
        conn.execute("INSERT INTO visits DEFAULT VALUES")
        count = conn.execute("SELECT count(*) FROM visits").fetchone()[0]
    return {"message": "Hello from onboarding-app", "visits": count}


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
