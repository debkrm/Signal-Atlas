"""
base.py - Pure Strategy contract interface for Signal Atlas.

All strategies must be pure functions without side effects, network calls, or database I/O.
Input: historical features, market context, universe, and explicit parameters.
Output: candidate setups or explicit rejection reasons.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from signal_atlas.features.models import TechnicalFeatures
from signal_atlas.strategy.models import MarketContext, SignalState, StrategyCandidate, StrategyParameters
from signal_atlas.universe.models import UniverseMember


class Strategy(ABC):
    """
    Abstract base class for pure deterministic quantitative strategies.
    Guarantees stable identity, versioning, and zero I/O side effects.
    """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique, stable strategy identifier."""
        pass

    @property
    @abstractmethod
    def strategy_version(self) -> str:
        """Semantic version of the strategy algorithm."""
        pass

    @abstractmethod
    def evaluate_candidate(
        self,
        features: TechnicalFeatures,
        market_context: MarketContext,
        universe_member: Optional[UniverseMember] = None,
    ) -> StrategyCandidate:
        """
        Pure function evaluating a single instrument's technical features on day t.
        Returns a StrategyCandidate with state BUY or AVOID.
        """
        pass

    def evaluate_universe(
        self,
        features_by_instrument: Dict[str, TechnicalFeatures],
        universe_members: Sequence[UniverseMember],
        market_context: MarketContext,
    ) -> List[StrategyCandidate]:
        """
        Evaluates an entire point-in-time universe.
        Sorts generated BUY candidates by reward-to-risk descending.
        """
        candidates: List[StrategyCandidate] = []
        for member in universe_members:
            if not member.is_eligible:
                continue
            feats = features_by_instrument.get(member.instrument_id)
            if feats is None:
                continue
            cand = self.evaluate_candidate(feats, market_context, member)
            candidates.append(cand)

        # Sort BUY setups by reward_to_risk desc, then symbol asc
        candidates.sort(
            key=lambda c: (
                0 if c.signal_state.value == "BUY" else 1,
                -c.reward_to_risk if c.signal_state.value == "BUY" else Decimal("0"),
                c.symbol,
            )
        )
        return candidates

    def evaluate_next_session_entry(
        self,
        candidate: StrategyCandidate,
        next_open: Decimal,
        next_high: Decimal,
        next_low: Decimal,
    ) -> Tuple[bool, Optional[Decimal], Optional[str]]:
        """
        Validates signal execution on next-session (t+1) opening.
        Default implementation fills at next_open if valid BUY signal and within boundaries.
        """
        if candidate.signal_state != SignalState.BUY or not candidate.is_valid:
            return False, None, "NOT_A_BUY_SIGNAL"

        if next_open <= candidate.stop_loss:
            return False, None, f"GAPPED_BELOW_STOP: Open {next_open} <= Stop {candidate.stop_loss}"

        if next_open >= candidate.target_price:
            return False, None, f"GAPPED_TO_TARGET: Open {next_open} >= Target {candidate.target_price}"

        ref = candidate.entry_reference
        if ref > Decimal("0"):
            gap_pct = abs(next_open - ref) / ref
            if gap_pct > Decimal("0.02"):
                return False, None, f"OPENING_GAP_TOO_LARGE: {gap_pct:.2%} exceeds 2.00%"

        return True, next_open, None


