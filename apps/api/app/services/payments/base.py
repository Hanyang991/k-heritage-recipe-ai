"""Payments adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class BillingResult:
    success: bool
    billing_key: str
    customer_key: str
    message: str = ""


class PaymentsAdapter(Protocol):
    def confirm_billing(self, auth_key: str, customer_key: str) -> BillingResult:
        """Exchange a one-time auth key for a permanent billing key."""

    def charge_monthly(self, billing_key: str, amount_krw: int) -> BillingResult:
        """Run the monthly charge against a saved billing key."""

    def cancel(self, billing_key: str) -> BillingResult:
        """Cancel billing — also deletes the billing key on Toss's side."""
