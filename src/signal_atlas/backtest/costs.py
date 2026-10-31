"""
costs.py - Effective-Dated Transaction Cost & Slippage Models for NSE Cash Equities.

Simulates real Indian regulatory, exchange, and brokerage charges for delivery equity trades:
- STT (Securities Transaction Tax): 0.1% on buy and 0.1% on sell (delivery)
- NSE Exchange Transaction Fee: ~0.00297%
- SEBI Charges: 0.0001% (₹10/crore)
- Stamp Duty: 0.015% on buy delivery
- GST: 18% on (Brokerage + Exchange Fee + SEBI Charges)
- Brokerage: Configurable flat fee or percentage (default: ₹20 per executed order or 0.03%)
- Slippage: Configurable execution friction (e.g. 5-10 bps)
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import NamedTuple
from pydantic import BaseModel


class ExecutionCostBreakdown(NamedTuple):
    gross_amount: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_charges: Decimal
    sebi_charges: Decimal
    stamp_duty: Decimal
    gst: Decimal
    slippage: Decimal
    total_charges: Decimal
    net_cash_flow: Decimal  # -(gross + charges) on buy, +(gross - charges) on sell


class TransactionCostModel(BaseModel):
    """
    Configurable transaction cost model for delivery-only swing trading.
    """
    brokerage_per_order: Decimal = Decimal("20.00")
    brokerage_pct: Decimal = Decimal("0.0003")  # 0.03% max brokerage
    stt_rate: Decimal = Decimal("0.0010")       # 0.10% delivery STT
    exchange_rate: Decimal = Decimal("0.0000297")  # NSE txn charge
    sebi_rate: Decimal = Decimal("0.000001")    # SEBI turnover charge
    stamp_duty_buy_rate: Decimal = Decimal("0.00015")  # 0.015% state stamp duty
    gst_rate: Decimal = Decimal("0.18")         # 18% GST on services
    slippage_bps: Decimal = Decimal("0.0005")   # 5 bps standard slippage

    def calculate_buy_costs(self, price: Decimal, quantity: int) -> ExecutionCostBreakdown:
        """
        Calculates all inclusive execution costs for a delivery BUY order.
        """
        gross = price * Decimal(quantity)
        slip = (gross * self.slippage_bps).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        exec_gross = gross + slip

        # Brokerage is min(flat, pct)
        brok = min(self.brokerage_per_order, exec_gross * self.brokerage_pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        stt = (exec_gross * self.stt_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        exchange = (exec_gross * self.exchange_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sebi = (exec_gross * self.sebi_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stamp = (exec_gross * self.stamp_duty_buy_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # GST applies to Brokerage + Exchange + SEBI
        gst_taxable = brok + exchange + sebi
        gst = (gst_taxable * self.gst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_fees = brok + stt + exchange + sebi + stamp + gst + slip
        net_flow = -(exec_gross + brok + stt + exchange + sebi + stamp + gst)

        return ExecutionCostBreakdown(
            gross_amount=gross,
            brokerage=brok,
            stt=stt,
            exchange_charges=exchange,
            sebi_charges=sebi,
            stamp_duty=stamp,
            gst=gst,
            slippage=slip,
            total_charges=total_fees,
            net_cash_flow=net_flow,
        )

    def calculate_sell_costs(self, price: Decimal, quantity: int) -> ExecutionCostBreakdown:
        """
        Calculates all inclusive execution costs for a delivery SELL order.
        """
        gross = price * Decimal(quantity)
        slip = (gross * self.slippage_bps).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        exec_gross = gross - slip

        brok = min(self.brokerage_per_order, exec_gross * self.brokerage_pct).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        stt = (exec_gross * self.stt_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        exchange = (exec_gross * self.exchange_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sebi = (exec_gross * self.sebi_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stamp = Decimal("0.00")  # Stamp duty paid only by buyer

        gst_taxable = brok + exchange + sebi
        gst = (gst_taxable * self.gst_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_fees = brok + stt + exchange + sebi + stamp + gst + slip
        net_flow = exec_gross - (brok + stt + exchange + sebi + gst)

        return ExecutionCostBreakdown(
            gross_amount=gross,
            brokerage=brok,
            stt=stt,
            exchange_charges=exchange,
            sebi_charges=sebi,
            stamp_duty=stamp,
            gst=gst,
            slippage=slip,
            total_charges=total_fees,
            net_cash_flow=net_flow,
        )
