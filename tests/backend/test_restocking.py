"""
Tests for restocking API endpoints.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Submitted orders are module-level state, so reset them around every test."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_get_restock_recommendations(self, client):
        """Test getting restocking recommendations."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert isinstance(data["candidates"], list)
        assert len(data["candidates"]) > 0

        first = data["candidates"][0]
        for field in [
            "item_sku", "item_name", "trend", "current_demand", "forecasted_demand",
            "quantity_on_hand", "restock_quantity", "unit_cost", "line_cost", "lead_time_days",
        ]:
            assert field in first

    def test_recommendations_only_positive_quantities(self, client):
        """Test that fully stocked SKUs are excluded."""
        data = client.get("/api/restocking/recommendations").json()

        for candidate in data["candidates"]:
            assert candidate["restock_quantity"] > 0
            assert candidate["restock_quantity"] == (
                candidate["forecasted_demand"] - candidate["quantity_on_hand"]
            )

        # PSU-501 has 420 on hand against a forecast of 252
        skus = [c["item_sku"] for c in data["candidates"]]
        assert "PSU-501" not in skus

    def test_recommendations_line_cost_calculation(self, client):
        """Test that line costs and max budget are calculated correctly."""
        data = client.get("/api/restocking/recommendations").json()

        for candidate in data["candidates"]:
            expected = candidate["restock_quantity"] * candidate["unit_cost"]
            assert abs(candidate["line_cost"] - expected) < 0.01

        total = sum(c["line_cost"] for c in data["candidates"])
        assert abs(data["max_budget"] - total) < 0.01

    def test_recommendations_priority_order(self, client):
        """Test that candidates are ordered by trend, then demand growth."""
        candidates = client.get("/api/restocking/recommendations").json()["candidates"]
        rank = {"increasing": 0, "stable": 1, "decreasing": 2}

        keys = [
            (rank[c["trend"]], -(c["forecasted_demand"] - c["current_demand"]), c["item_sku"])
            for c in candidates
        ]
        assert keys == sorted(keys)
        assert candidates[0]["trend"] == "increasing"

    def test_get_restock_orders_empty(self, client):
        """Test that no orders exist before any are submitted."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restock_order(self, client):
        """Test submitting a restocking order."""
        response = client.post("/api/restocking/orders", json={
            "items": [
                {"sku": "WDG-001", "quantity": 100},
                {"sku": "MTR-304", "quantity": 2},
            ]
        })
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        assert "T" in order["submitted_date"]
        assert "T" in order["expected_delivery"]

    def test_create_restock_order_uses_server_prices(self, client):
        """Test that totals come from forecast data, not the request."""
        order = client.post("/api/restocking/orders", json={
            "items": [{"sku": "WDG-001", "quantity": 100, "unit_cost": 0.01}]
        }).json()

        line = order["items"][0]
        assert line["unit_cost"] == 12.5
        assert abs(line["line_total"] - 1250.0) < 0.01
        assert abs(order["total_cost"] - 1250.0) < 0.01

    def test_create_restock_order_lead_time_calculation(self, client):
        """Test that order lead time is the slowest item's lead time."""
        # GSK-203 takes 5 days, MTR-304 takes 21 days
        order = client.post("/api/restocking/orders", json={
            "items": [
                {"sku": "GSK-203", "quantity": 10},
                {"sku": "MTR-304", "quantity": 1},
            ]
        }).json()

        assert order["lead_time_days"] == 21

    def test_created_order_appears_in_list(self, client):
        """Test that submitted orders are listed newest first."""
        first = client.post("/api/restocking/orders", json={
            "items": [{"sku": "WDG-001", "quantity": 1}]
        }).json()
        second = client.post("/api/restocking/orders", json={
            "items": [{"sku": "BRG-102", "quantity": 1}]
        }).json()

        orders = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in orders] == [second["id"], first["id"]]
        assert first["order_number"] != second["order_number"]

    def test_create_restock_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restock_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post("/api/restocking/orders", json={
            "items": [{"sku": "NOPE-999", "quantity": 1}]
        })
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_create_restock_order_non_positive_quantity(self, client):
        """Test that a zero quantity is rejected."""
        response = client.post("/api/restocking/orders", json={
            "items": [{"sku": "WDG-001", "quantity": 0}]
        })
        assert response.status_code == 400

        # A rejected order must not be stored
        assert client.get("/api/restocking/orders").json() == []
