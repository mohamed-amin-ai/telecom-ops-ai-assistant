from app.tools import get_ticket


def test_get_ticket_invalid_id_returns_none_without_touching_the_db():
    # Malformed ids must short-circuit before any database call is attempted.
    assert get_ticket("not-a-ticket-id") is None
    assert get_ticket("") is None
    assert get_ticket("INC-") is None
