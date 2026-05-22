"""TossPayments adapter factory."""

from functools import lru_cache

from app.config import get_settings
from app.services.payments.base import PaymentsAdapter
from app.services.payments.mock import MockPaymentsAdapter


@lru_cache
def get_payments_adapter() -> PaymentsAdapter:
    settings = get_settings()
    if settings.payments_provider == "live":
        raise NotImplementedError(
            "Live TossPayments adapter is not yet wired. "
            "Use PAYMENTS_PROVIDER=mock for development."
        )
    return MockPaymentsAdapter()


__all__ = ["PaymentsAdapter", "get_payments_adapter"]
