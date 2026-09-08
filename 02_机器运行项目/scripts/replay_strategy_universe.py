"""独立进程从同一冻结Parquet复跑全部模块；可与主计算并行，无数据库查询。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import json
import time
import pandas as pd
from covered_call.margin_engine import PreparedMarket,run_margin_backtest
from covered_call.universe_config import registry
from verify_strategy_universe import load_snapshot
from run_strategy_universe import digest_frames


def replay(out):
    out=Path(out);manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
    prepared=PreparedMarket(load_snapshot(out/'data_snapshot'));results=[];clock=time.perf_counter()
    for idx,param in enumerate(registry().to_dict('records')):
        for scenario_id,scenario in manifest['scenarios'].items():
            for period in ['FULL_HISTORY','COMMON_PERIOD']:
                independent=not(param['selection_method']=='DELTA' and period=='COMMON_PERIOD')
                if independent:
                    start=manifest['common_period_start'] if period=='COMMON_PERIOD' or param['selection_method']=='DELTA' else manifest['full_history_start']
                    frames,status=run_margin_backtest(prepared,param,start,manifest['end_date'],scenario,manifest['defaults'])
                    digest=digest_frames(frames)
                results.append(dict(strategy_id=param['strategy_id'],scenario_id=scenario_id,period_id=period,
                    replayed_sha256=digest,independent_execution=independent,run_id=manifest['run_id'],source_hash=manifest['source_hash']))
        if (idx+1)%48==0:
            print(f'独立复跑 {idx+1}/576; {time.perf_counter()-clock:.1f}s',flush=True)
    result=pd.DataFrame(results)
    if len(result)!=2304 or result.duplicated(['strategy_id','scenario_id','period_id']).any(): raise AssertionError('复跑不完整')
    result.to_parquet(out/'replayed_result_hashes.parquet',index=False)
    print('REPLAY COMPUTED; pending comparison with original hashes',flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--run',required=True)
    replay(parser.parse_args().run)
