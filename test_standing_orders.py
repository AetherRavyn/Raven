from __future__ import annotations

from app.core.standing_orders import StandingOrderStore


def test_standing_orders_parse_and_render(tmp_path) -> None:
    store = StandingOrderStore(str(tmp_path))
    store.save_raw(
        "# Standing Orders\n- compliance | always check compliance before replying\n"
    )
    orders = store.parse()
    assert len(orders) == 1
    rendered = store.render(orders)
    assert "compliance" in rendered
