"""固定规则枚举；不读取收益，不筛选、不排序策略表现。"""
from itertools import product
import pandas as pd

PARAMETER_VERSION = 'CC_UNIVERSE_1.1'
ENGINE_VERSION = 'atomic_margin_1.1'
SCENARIOS = {
    'BASE': {'option_slippage': .005, 'option_commission': 2., 'financing_rate': .06},
    'STRESS': {'option_slippage': .01, 'option_commission': 2., 'financing_rate': .08},
}
DEFAULTS = dict(initial_capital=1_000_000., min_dte=7, max_dte=90,
                etf_commission_rate=.0001, etf_min_commission=0.,
                etf_slippage_rate=0., etf_lot_size=100, cash_interest_rate=0.,
                exclude_adjusted_new_entries=True, require_valid_t1=True)


def strategy_id(method, target, dte, roll, coverage):
    prefix = f'D{round(target*100):02d}' if method == 'DELTA' else (
        'ATM' if target == 0 else f'OTM{round(target*100):02d}')
    return f'CC_{prefix}_DTE{dte}_R{roll}_C{round(coverage*100)}'


def registry():
    rows = []
    for method, targets in [('DELTA', [.10,.15,.20,.25,.30,.35]),
                            ('MONEYNESS', [0.,.02,.03,.05,.08,.10])]:
        for target, dte, roll, coverage in product(targets, [20,30,45,60], [1,3,5,10], [.5,.75,1.]):
            rows.append(dict(strategy_id=strategy_id(method,target,dte,roll,coverage),
                strategy_family='COVERED_CALL', selection_method=method,
                target_delta=target if method=='DELTA' else None,
                target_otm=target if method=='MONEYNESS' else None,
                target_dte=dte, roll_dte=roll, coverage_ratio=coverage,
                parameter_version=PARAMETER_VERSION))
    result = pd.DataFrame(rows)
    assert len(result) == result.strategy_id.nunique() == 576
    assert result.groupby('selection_method').size().eq(288).all()
    return result
