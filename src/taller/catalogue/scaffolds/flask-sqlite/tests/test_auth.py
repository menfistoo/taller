from auth import login_required


def test_a_protected_view_refuses_an_anonymous_request(app):
    app.add_url_rule("/private", "private", login_required(lambda: "secret"))

    assert app.test_client().get("/private").status_code == 401
