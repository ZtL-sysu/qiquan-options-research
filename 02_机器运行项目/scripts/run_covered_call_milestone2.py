"""固定两策略、两成本情景，不做参数优化。"""
from pathlib import Path
from datetime import datetime
import argparse
import json
import hashlib
import sys
import pandas as pd
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from covered_call.data import load_market, json_write
from covered_call.engine import run_backtest
from covered_call.metrics import metrics, independent_reconciliation, source_reconciliation

EMPTY_COLUMNS={
    'roll_events':['roll_id','signal_date','execution_date','old_contract','new_contract','old_closed','new_opened','status'],
    'dividend_ledger':['date','shares_entitled','dividend_per_share','dividend_accrual','actual_payment_date','convention'],
    'missed_trade_log':['signal_date','execution_date','option_code','side','reason','roll_id'],
    'missing_signal_log':['signal_date','planned_execution_date','reason','strategy'],
    'corporate_action_log':['date','option_code','contracts','old_multiplier','new_multiplier','coverage_ratio'],
    'trades':['trade_id','signal_date','execution_date','instrument','option_code','side','contracts','strike','DTE','spot','moneyness','delta_wind','IV_wind','market_close','execution_price','slippage','commission','trade_reason'],
}


def run(config):
    cfg=yaml.safe_load(Path(config).read_text(encoding='utf-8'))
    if cfg['cash_policy'] not in ['stop','finance']:
        raise ValueError('cash_policy需为stop或明确指定的finance')
    market=load_market()
    manifest=json.loads((ROOT/'data_mart/manifest.json').read_text(encoding='utf-8'))
    end=manifest['end_date'];full=manifest['start_date'];common=manifest['wind_delta_first_date']
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+cfg['cash_policy']
    out=ROOT/'outputs'/'milestone2'/run_id;out.mkdir(parents=True)
    source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['covered_call','scripts','tests'] for p in (ROOT/folder).glob('*.py')}
    json_write({'run_id':run_id,'config':cfg,'data_manifest':manifest,'source_sha256':source_hashes},out/'run_manifest.json')
    summary=[];benchmarks={}

    def export(frames,status,name,benchmark):
        directory=out/name;directory.mkdir()
        checks=independent_reconciliation(frames,cfg)
        frames['independent_reconciliation']=checks
        frames['source_reconciliation']=source_reconciliation(frames,market)
        results,month,year=metrics(frames,benchmark,cfg,status)
        for table,frame in frames.items():
            if frame.empty and not len(frame.columns):
                frame=pd.DataFrame(EMPTY_COLUMNS.get(table,['date']))
            frame.to_csv(directory/(table+'.csv'),index=False,encoding='utf-8-sig')
        month.rename('收益率').rename_axis('月份').to_csv(directory/'monthly_returns.csv',encoding='utf-8-sig')
        year.rename('收益率').rename_axis('年份').to_csv(directory/'annual_returns.csv',encoding='utf-8-sig')
        json_write(results,directory/'metrics.json');json_write(status,directory/'status.json')
        json_write(cfg,directory/'parameters.json')
        summary.append({'run':name,**{k:v for k,v in results.items() if not isinstance(v,dict)},'halt_reason':status['reason']})
        print(name,'completed=',status['completed'],'last=',status['last_valid_date'],'net=',results.get('net_return'),'reason=',status['reason'],flush=True)

    for period,start in [('full',full),('common',common)]:
        b,status=run_backtest(market,'BUY_HOLD',start,end,cfg,0.)
        benchmarks[period]=b['daily_nav']
        export(b,status,'BUY_HOLD_'+period,b['daily_nav'])
    for scenario,slip in [('base',cfg['option_slippage_base']),('stress',cfg['option_slippage_stress'])]:
        for strategy,period,start in [('CC_OTM_5','full',full),('CC_OTM_5','common',common),('CC_DELTA_025','common',common)]:
            frames,status=run_backtest(market,strategy,start,end,cfg,slip)
            frames['benchmark_daily_nav']=benchmarks[period]
            name=f'{strategy}_{period}_{scenario}'
            export(frames,status,name,benchmarks[period])
            json_write({**cfg,'option_slippage_rate':slip,'strategy':strategy,'signal_start':start,'requested_end':end},out/name/'parameters.json')
    pd.DataFrame(summary).to_csv(out/'comparison_summary.csv',index=False,encoding='utf-8-sig')
    json_write({'run_id':run_id,'output_dir':str(out)},ROOT/'outputs'/'milestone2'/'latest_run.json')
    print('OUTPUT',out,flush=True)
    return out


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(ROOT/'config/covered_call.yaml'))
    args=parser.parse_args();run(args.config)
