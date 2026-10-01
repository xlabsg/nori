from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Holding(StrictModel):
    asset_id: str = Field(min_length=1, max_length=120)
    quantity: Amount
    price: Amount | None = None


class CashFlow(StrictModel):
    kind: Literal["deposit", "withdrawal"]
    amount: Amount
    external: bool = True


class AnalysisInput(StrictModel):
    currency: Literal["USD", "USDT", "USDC", "CNY"] = "USD"
    observed_at: AwareDatetime
    source: str = Field(min_length=1, max_length=200)
    opening_equity: Amount | None = None
    closing_equity: Amount | None = None
    cash_flows: list[CashFlow] = Field(default_factory=list, max_length=500)
    holdings: list[Holding] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def valid_input(self):
        if (self.opening_equity is None) != (self.closing_equity is None):
            raise ValueError("Provide both opening_equity and closing_equity")
        if self.opening_equity is None and not self.holdings:
            raise ValueError("Provide equity values or at least one holding")
        if self.cash_flows and self.opening_equity is None:
            raise ValueError("Cash flows require equity values")
        identifiers = [holding.asset_id for holding in self.holdings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Duplicate asset_id; aggregate each asset before importing")
        return self


class TaskCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=120)
    input: AnalysisInput


class MonitorCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    interval_seconds: int = Field(ge=60, le=2592000)
    input: AnalysisInput


class ImportCSV(StrictModel):
    csv: str = Field(max_length=200000)
    currency: Literal["USD", "USDT", "USDC", "CNY"] = "USD"
    observed_at: AwareDatetime
    source: str = Field(min_length=1, max_length=200)


def utc_string(value: datetime) -> str:
    return value.isoformat()
