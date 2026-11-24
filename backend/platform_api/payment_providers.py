"""Verified payment event contract. The enabled implementation is local only."""
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class VerifiedPaymentEvent:
    provider: str
    id: str
    order_id: str
    kind: Literal["paid", "failed", "refunded"]
    amount_cents: int
    currency: str


class PaymentProvider(Protocol):
    def verify_callback(self, raw_body: bytes, headers: dict[str, str]) -> VerifiedPaymentEvent:
        """Verify signatures, merchant and message freshness before constructing the event."""
        ...


def mock_event(order, kind):
    """Create a local event directly from the locked order, never from client amounts."""
    return VerifiedPaymentEvent(provider="local_mock", id=f"{order.id}:{kind}", order_id=order.id,
                                kind=kind, amount_cents=order.total_cents, currency="CNY")
