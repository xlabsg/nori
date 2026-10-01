from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.modules.analytics.calculations import analyze, import_csv
from finance_agent.modules.analytics.schemas import AnalysisInput, ImportCSV


def test_cash_flow_conservation(input_data):
    result = analyze(AnalysisInput.model_validate(input_data))["equity"]
    assert Decimal(result["profit"]) == Decimal(500)
    assert Decimal(result["closing"]) == (
        Decimal(result["opening"])
        + Decimal(result["external_net_flow"])
        + Decimal(result["profit"])
    )


def test_deposits_are_not_profit_and_internal_transfers_ignored(input_data):
    input_data["closing_equity"] = "12000"
    input_data["cash_flows"].append({"kind": "deposit", "amount": "9999", "external": False})
    assert analyze(AnalysisInput.model_validate(input_data))["equity"]["profit"] == "0"


def test_withdrawal_no_price_change(input_data):
    input_data["closing_equity"] = "9000"
    input_data["cash_flows"] = [{"kind": "withdrawal", "amount": "1000"}]
    assert analyze(AnalysisInput.model_validate(input_data))["equity"]["profit"] == "0"


def test_missing_price_not_zero(input_data):
    input_data["holdings"] = [
        {"asset_id": "bitcoin", "quantity": "0.1", "price": "60000"},
        {"asset_id": "unknown", "quantity": "100", "price": None},
    ]
    result = analyze(AnalysisInput.model_validate(input_data))
    portfolio = result["portfolio"]
    assert portfolio["complete"] is False
    assert portfolio["valued_total"] == "6000.0"
    assert portfolio["holdings"][1]["value"] is None
    assert portfolio["holdings"][1]["weight_of_valued_percent"] is None


def test_zero_total_has_no_weight(input_data):
    input_data["holdings"] = [{"asset_id": "zero", "quantity": "0", "price": "1"}]
    result = analyze(AnalysisInput.model_validate(input_data))
    assert result["portfolio"]["holdings"][0]["weight_of_valued_percent"] is None


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0.000000001"])
def test_invalid_financial_values(input_data, value):
    input_data["opening_equity"] = value
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(input_data)


def test_csv_preview_preserves_unpriced_assets():
    data = import_csv(
        ImportCSV(
            csv="asset_id,quantity,price\nbitcoin,0.1,60000\nunknown,5,\n",
            currency="USD",
            observed_at="2026-10-01T00:00:00Z",
            source="test-csv",
        )
    )
    assert data.holdings[1].price is None
    assert data.holdings[0].quantity == Decimal("0.1")


def test_csv_duplicate_assets_rejected():
    with pytest.raises(ValidationError):
        import_csv(
            ImportCSV(
                csv="asset_id,quantity,price\nbitcoin,1,2\nbitcoin,2,3\n",
                observed_at="2026-10-01T00:00:00Z",
                source="test-csv",
            )
        )


def test_naive_timestamp_rejected(input_data):
    input_data["observed_at"] = "2026-10-01T00:00:00"
    with pytest.raises(ValidationError):
        AnalysisInput.model_validate(input_data)
