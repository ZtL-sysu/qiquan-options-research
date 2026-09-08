"""以原M2 pandas选约器独立核对快速选约缓存，固定随机20日期×48目标组合。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import pandas as pd
from verify_strategy_universe import load_snapshot
from covered_call.margin_engine import PreparedMarket
from covered_call.selection import select_contract
from covered_call.universe_config import registry,DEFAULTS


def audit(out):
    out=Path(out);market=load_snapshot(out/'data_snapshot');prepared=PreparedMarket(market)
    params=registry().drop_duplicates(['selection_method','target_delta','target_otm','target_dte'])
    dates=pd.Series(sorted(prepared.days)).sample(n=20,random_state=20260828).sort_values();checks=[]
    for date in dates:
        day=market['options'].loc[market['options'].date.eq(date)]
        for param in params.to_dict('records'):
            cfg=dict(DEFAULTS,target_dte=param['target_dte'],target_delta=param['target_delta'],target_moneyness=1+param['target_otm'])
            cfg['next_execution_date']=prepared.calendar[prepared.calendar.searchsorted(date,side='right')]
            actual,ar=prepared.select(date,param,cfg)
            expected,er=select_contract(day,date,prepared.underlying[date],
                'CC_DELTA_025' if param['selection_method']=='DELTA' else 'CC_OTM_5',cfg)
            a=actual['option_code'] if actual else None;e=expected['option_code'] if expected else None
            checks.append(dict(date=date,selection_method=param['selection_method'],target_delta=param['target_delta'],
                target_otm=param['target_otm'],target_dte=param['target_dte'],actual=a,reference=e,identical=(a==e and ar==er)))
    result=pd.DataFrame(checks);result.to_parquet(out/'selection_reference_audit.parquet',index=False)
    if not result.identical.all(): raise AssertionError('快速选约与原pandas规则不同')
    print(f'{len(result)} reference selections matched',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);audit(parser.parse_args().run)
