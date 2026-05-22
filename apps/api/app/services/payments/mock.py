"""Mock payments adapter — always succeeds, returns deterministic billing keys."""

from __future__ import annotations

import hashlib

from app.services.payments.base import BillingResult, PaymentsAdapter


class MockPaymentsAdapter(PaymentsAdapter):
    def confirm_billing(self, auth_key: str, customer_key: str) -> BillingResult:
        key = "mock_bkey_" + hashlib.sha1(f"{auth_key}|{customer_key}".encode()).hexdigest()[:16]
        return BillingResult(
            success=True, billing_key=key, customer_key=customer_key, message="mock-confirmed"
        )

    def charge_monthly(self, billing_key: str, amount_krw: int) -> BillingResult:
        return BillingResult(
            success=True,
            billing_key=billing_key,
            customer_key="",
            message=f"mock-charged-{amount_krw}KRW",
        )

    def cancel(self, billing_key: str) -> BillingResult:
        return BillingResult(
            success=True, billing_key="", customer_key="", message="mock-cancelled"
        )
