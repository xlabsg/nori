import csv
import io
from decimal import Decimal, localcontext

from finance_agent.modules.analytics.schemas import AnalysisInput, ImportCSV


def analyze(data: AnalysisInput) -> dict:
    with localcontext() as context:
        context.prec = 80
        result = {
            "method_version": "snapshot-v1",
            "currency": data.currency,
            "observed_at": data.observed_at.isoformat(),
            "source": data.source,
            "data_mode": "imported_snapshot",
            "warnings": ["Imported data; this report is not a live market or account feed."],
        }
        if data.opening_equity is not None:
            net_flow = sum(
                (
                    flow.amount if flow.kind == "deposit" else -flow.amount
                    for flow in data.cash_flows
                    if flow.external
                ),
                Decimal(0),
            )
            change = data.closing_equity - data.opening_equity
            result["equity"] = {
                "opening": format(data.opening_equity, "f"),
                "closing": format(data.closing_equity, "f"),
                "change": format(change, "f"),
                "external_net_flow": format(net_flow, "f"),
                "profit": format(change - net_flow, "f"),
                "formula": "closing - opening - external_net_flow",
                "coverage": "user_supplied_equity_and_cash_flows",
            }
        if data.holdings:
            valued = [holding for holding in data.holdings if holding.price is not None]
            total = sum((holding.quantity * holding.price for holding in valued), Decimal(0))
            result["portfolio"] = {
                "valued_total": format(total, "f"),
                "valued_assets": len(valued),
                "total_assets": len(data.holdings),
                "complete": len(valued) == len(data.holdings),
                "holdings": [
                    {
                        "asset_id": holding.asset_id,
                        "value": (
                            format(holding.quantity * holding.price, "f")
                            if holding.price is not None
                            else None
                        ),
                        "weight_of_valued_percent": (
                            format(
                                (holding.quantity * holding.price / total * 100).quantize(
                                    Decimal("0.0001")
                                ),
                                "f",
                            )
                            if holding.price is not None and total > 0
                            else None
                        ),
                    }
                    for holding in data.holdings
                ],
            }
            if len(valued) != len(data.holdings):
                result["warnings"].append(
                    "Unpriced assets excluded; weights cover valued assets only."
                )
        return result


def import_csv(request: ImportCSV) -> AnalysisInput:
    reader = csv.DictReader(io.StringIO(request.csv))
    if reader.fieldnames != ["asset_id", "quantity", "price"]:
        raise ValueError("Expected CSV columns: asset_id,quantity,price")
    rows = []
    for row in reader:
        if len(rows) >= 500 or None in row or any(value is None for value in row.values()):
            raise ValueError("CSV contains too many rows or malformed columns")
        rows.append({**row, "price": row["price"].strip() or None})
    return AnalysisInput(
        currency=request.currency,
        observed_at=request.observed_at,
        source=request.source,
        holdings=rows,
    )
