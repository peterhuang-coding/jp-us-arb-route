import pytest
from fastapi.testclient import TestClient

from arb import db, web_api


BOOLEAN_FIELDS = ["budget_cny", "customs_limit_cny"]


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_basket_api_rejects_boolean_numeric_fields(monkeypatch, field, value):
    def fail_if_db_touched(*args, **kwargs):
        raise AssertionError("database must not be touched during request validation")

    monkeypatch.setattr(db, "connect", fail_if_db_touched)
    client = TestClient(web_api.app, raise_server_exceptions=True)

    resp = client.post("/api/basket", json={field: value})

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(part == field for error in detail for part in error["loc"])


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
@pytest.mark.parametrize("value,expected", [("20.0", 20.0), (20, 20.0), (20.0, 20.0), (0, 0.0)])
def test_basket_request_accepts_non_boolean_numeric_values(field, value, expected):
    request = web_api.BasketRequest(**{field: value})

    assert getattr(request, field) == expected


def test_basket_request_rejects_negative_numeric_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        web_api.BasketRequest(budget_cny=-0.1)
    with pytest.raises(ValidationError):
        web_api.BasketRequest(customs_limit_cny=-0.1)
