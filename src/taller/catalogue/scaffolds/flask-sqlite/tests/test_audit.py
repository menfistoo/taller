import audit
import database


def test_an_event_is_recorded_and_read_back(app):
    path = app.config["DATABASE"]
    audit.record("payment.refund", actor="owner", detail={"amount": 10}, path=path)

    events = database.audit_events(path)

    assert [(e["action"], e["actor"]) for e in events] == [("payment.refund", "owner")]
