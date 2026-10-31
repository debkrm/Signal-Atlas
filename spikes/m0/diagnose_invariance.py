from decimal import Decimal, ROUND_HALF_UP
from signal_atlas.db.session import get_db
from signal_atlas.db.models import DailyPriceRaw, CorporateAction
from signal_atlas.quality.adjustment import apply_backward_adjustment
from sqlalchemy import select

with get_db() as db:
    cas = db.execute(select(CorporateAction).where(
        CorporateAction.action_type.in_(['STOCK_SPLIT', 'BONUS_ISSUE']),
        CorporateAction.share_multiplier > Decimal('1.0'),
        CorporateAction.verification_status == 'VERIFIED'
    )).scalars().all()
    ca_by_inst = {}
    for ca in cas:
        ca_by_inst.setdefault(ca.instrument_id, []).append(ca)

    bad = 0
    total = 0
    for inst_id, actions in ca_by_inst.items():
        prices = db.execute(select(DailyPriceRaw).where(DailyPriceRaw.instrument_id == inst_id)).scalars().all()
        raw_dicts = [{
            'trade_date': p.trade_date, 'open': p.open, 'high': p.high, 'low': p.low, 'close': p.close,
            'last': p.last, 'prev_close': p.prev_close, 'volume': p.volume, 'traded_value': p.traded_value
        } for p in prices]
        adj = apply_backward_adjustment(raw_dicts, actions)
        for a, r in zip(adj, raw_dicts):
            total += 1
            raw_close = Decimal(str(r['close']))
            raw_vol = Decimal(r['volume'])
            raw_prod = (raw_close * raw_vol)
            adj_prod = (a.close * a.volume)
            diff = abs(adj_prod - raw_prod)
            if diff > Decimal('0.01'):
                bad += 1
                if bad <= 5:
                    print(f"Symbol: {actions[0].symbol}, Date: {a.trade_date}, Mult: {a.cumulative_multiplier}")
                    print(f"  raw_close: {raw_close}, raw_vol: {raw_vol}, raw_prod: {raw_prod}")
                    print(f"  adj_close: {a.close}, adj_vol: {a.volume}, adj_prod: {adj_prod}")
                    print(f"  diff: {diff}")
    print(f"Total checked: {total}, bad: {bad}")
