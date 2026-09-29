import database


def test_the_home_page_renders(client):
    assert client.get("/").status_code == 200


def test_the_database_runs_in_wal_mode(app):
    with database.get_db(app.config["DATABASE"]) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
