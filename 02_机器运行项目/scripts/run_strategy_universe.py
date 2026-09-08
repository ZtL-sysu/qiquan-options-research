"""全量固定规则遍历。无优化目标、无收益排序、无SQL循环。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import shutil
import time
import zipfile
from datetime import datetime
import numpy as np
import pandas as pd
from covered_call.data import ROOT,MART,load_market,json_write
from covered_call.margin_engine import PreparedMarket,run_margin_backtest
from covered_call.universe_config import registry,SCENARIOS,DEFAULTS,PARAMETER_VERSION,ENGINE_VERSION
from covered_call.universe_analytics import reliable_delta_history,market_states,add_benchmark,metrics,regime_metrics,audit_frames
from covered_call.universe_io import LongTables,attach_metadata,normalize,EVENT_COLUMNS


def digest_frames(frames):
    h=hashlib.sha256()
    for key in sorted(frames):
        h.update(key.encode());h.update(pd.util.hash_pandas_object(frames[key],index=False).to_numpy().tobytes())
        h.update('|'.join(frames[key].columns).encode())
    return h.hexdigest()


def main(baseline_only=False):
    run_id=datetime.now().strftime('%Y%m%d_%H%M%S')
    out=ROOT/'outputs'/'strategy_universe'/run_id
    # 同秒重复启动必须显式失败，不能混写同一批次。
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((MART/'manifest.json').read_text(encoding='utf-8'))
    source_hash=hashlib.sha256(json.dumps(manifest['file_sha256'],sort_keys=True).encode()).hexdigest()
    data_version=manifest['end_date']+'_'+source_hash[:12]
    code_files=sorted([*ROOT.glob('covered_call/*.py'),*ROOT.glob('scripts/*.py'),*ROOT.glob('tests/*.py'),
                       *ROOT.glob('data_audit/*.py'),*ROOT.glob('config/*.yaml')])
    code_hash=hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+p.read_bytes() for p in code_files)).hexdigest()
    with zipfile.ZipFile(out/'source_code_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in code_files: z.write(p,p.relative_to(ROOT))
    for relative in manifest['file_sha256']:
        dest=out/'data_snapshot'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(MART/relative,dest)
    shutil.copy2(MART/'manifest.json',out/'data_snapshot'/'manifest.json')
    json_write(dict(run_id=run_id,status='RUNNING'),out/'run_status.json')
    base_meta=dict(run_id=run_id,parameter_version=PARAMETER_VERSION,data_version=data_version,
                   source_hash=source_hash,engine_version=ENGINE_VERSION+'_'+code_hash[:12])
    print('读取一次标准Parquet，并准备共享行情...',flush=True)
    market=load_market();prepared=PreparedMarket(market)
    common,profile,reliability=reliable_delta_history(market)
    profile.to_parquet(out/'delta_quality_daily.parquet',index=False)
    start=pd.Timestamp(manifest['start_date']);end=pd.Timestamp(manifest['end_date'])
    json_write(dict(**base_meta,code_sha256=code_hash,scenarios=SCENARIOS,defaults=DEFAULTS,
        reliability=reliability,full_history_start=str(start.date()),common_period_start=str(common.date()),
        end_date=str(end.date()),source_manifest=manifest,baseline_only=baseline_only,
        rule_notes={'roll':'trading_DTE<=R at T, execute T+1; no next-month override; same-contract rolls charged both sides',
                    'financing':'explicit debt and cash; net atomic settlement; cash sweep repay; ACT/365 calendar days',
                    'fallback':'no cross-source delta; failed roll waits; expiry close-only risk exception logged',
                    'tie_break':'expiry>known next trading date; closest calendar DTE then earlier expiry; closest delta/moneyness then lower strike then code',
                    'latest_state':'primary latest_state BASE only exactly576; scenarios table separately1152',
                    'periods':'root FULL_HISTORY (Delta reliable history); common_period independently initialized OTM, identical Delta copied',
                    'financing_limit':'no broker credit limit assumed; halt if NAV<=0; all debt and maximum debt/NAV reported'}),out/'run_manifest.json')
    print('Wind Delta可靠起点',common.date(),'截至',end.date(),flush=True)
    # 必须先完成原M2期限设定的全历史BASE/STRESS验证，才生成遍历结果。
    baseline_results=[];bw=LongTables(out/'baseline')
    for method in ['MONEYNESS','DELTA']:
        param=dict(strategy_id='BASELINE_'+method,selection_method=method,target_delta=.25,target_otm=.05,
                   target_dte=35,roll_dte=2,coverage_ratio=1.)
        for scenario_id,scenario in SCENARIOS.items():
            begin=start if method=='MONEYNESS' else common
            f,status=run_margin_backtest(prepared,param,begin,end,scenario,dict(min_dte=25,max_dte=45))
            audit=audit_frames(f,prepared,param)
            for key in ['daily','trades','rolls','ledger']:
                bw.append(key,attach_metadata(f[key],dict(strategy_id=param['strategy_id'],scenario_id=scenario_id)))
            baseline_results.append(dict(strategy_id=param['strategy_id'],scenario_id=scenario_id,
                **status,final_NAV=float(f['daily'].NAV.iloc[-1]),maximum_financing=float(f['daily'].financing_balance.max()),audit=audit))
            print('baseline',method,scenario_id,status['completed'],status['failure_reason'],flush=True)
    bw.close();json_write(baseline_results,out/'baseline_validation.json')
    if not all(r['completed'] for r in baseline_results):
        json_write(dict(run_id=run_id,status='BASELINE_FAILED'),out/'run_status.json')
        raise RuntimeError('baseline未完整运行，禁止参数遍历，见baseline_validation.json')
    if baseline_only:
        print('BASELINE PASSED',out,flush=True);return
    states=market_states(market,prepared);states.to_parquet(out/'market_state_daily.parquet',index=False)
    reg=registry();reg['data_start_date']=start
    reg['effective_start_date']=np.where(reg.selection_method.eq('DELTA'),common,start)
    reg['latest_date']=end;reg['status']='PENDING';reg['failure_reason']=''
    normalize(reg).to_parquet(out/'strategy_registry.parquet',index=False)
    benchmarks={}
    for period,begin in [('FULL_HISTORY',start),('COMMON_PERIOD',common)]:
        f,s=run_margin_backtest(prepared,dict(selection_method='BUY_HOLD'),begin,end,SCENARIOS['BASE'])
        if not s['completed']: raise AssertionError('基准失败')
        benchmarks[period]=f['daily']
    pd.concat([attach_metadata(v,dict(period_id=k,**base_meta)) for k,v in benchmarks.items()],ignore_index=True).to_parquet(out/'benchmark_daily.parquet',index=False)
    full=LongTables(out);common_writer=LongTables(out/'common_period')
    all_metrics={'FULL_HISTORY':[],'COMMON_PERIOD':[]};latest=[];audit_rows=[];hash_rows=[];timing=time.perf_counter()
    table_names=dict(daily='strategy_daily',trades='strategy_trades',rolls='strategy_rolls',ledger='strategy_cash_ledger',events='strategy_events')
    def publish(frames,param,scenario_id,period,status,audit,digest):
        writer=full if period=='FULL_HISTORY' else common_writer
        benchmark=benchmarks['COMMON_PERIOD' if param['selection_method']=='DELTA' else period]
        frames={**frames,'daily':add_benchmark(frames['daily'],benchmark)}
        meta=dict(strategy_id=param['strategy_id'],scenario_id=scenario_id,period_id=period,**base_meta)
        for key,name in table_names.items():
            frame=frames[key]
            if key=='events': frame=frame.reindex(columns=EVENT_COLUMNS)
            writer.append(name,attach_metadata(frame,meta))
        writer.append('strategy_regime_metrics',attach_metadata(regime_metrics(frames['daily'],states),meta))
        metric=dict(**metrics(frames,status),**meta);all_metrics[period].append(metric)
        last=frames['daily'].iloc[[-1]].copy()
        if not status['completed']:
            last['strategy_state']='STOPPED';last['next_action']='STOPPED'
        last['failure_reason']=status['failure_reason'];last['latest_date']=end
        last['is_current']=last.date.eq(end)
        last['current_option']=last.short_call_code;last['DTE']=last.calendar_DTE
        last['premium_received']=last.premium_received_cumulative;last['unrealized_option_pnl']=last.option_unrealized_pnl
        if period=='FULL_HISTORY': latest.append(attach_metadata(last,meta))
        audit_rows.append(dict(**meta,**audit,completed=status['completed'],failure_reason=status['failure_reason']))
        hash_rows.append(dict(**meta,content_sha256=digest))
    try:
        for idx,param in enumerate(reg.to_dict('records')):
            failures=[]
            for scenario_id,scenario in SCENARIOS.items():
                begin=common if param['selection_method']=='DELTA' else start
                frames,status=run_margin_backtest(prepared,param,begin,end,scenario)
                audit=audit_frames(frames,prepared,param);digest=digest_frames(frames)
                publish(frames,param,scenario_id,'FULL_HISTORY',status,audit,digest)
                if not status['completed']: failures.append(scenario_id+':'+status['failure_reason'])
                if param['selection_method']=='MONEYNESS':
                    frames,status=run_margin_backtest(prepared,param,common,end,scenario)
                    audit=audit_frames(frames,prepared,param);digest=digest_frames(frames)
                publish(frames,param,scenario_id,'COMMON_PERIOD',status,audit,digest)
                if not status['completed']: failures.append(scenario_id+' COMMON:'+status['failure_reason'])
            reg.loc[idx,'status']='STOPPED' if failures else 'COMPLETED'
            reg.loc[idx,'failure_reason']=';'.join(failures)
            if (idx+1)%24==0:
                normalize(reg).to_parquet(out/'strategy_registry.parquet',index=False)
                print(f'{idx+1}/576 modules; elapsed {time.perf_counter()-timing:.1f}s',flush=True)
    finally:
        full.close();common_writer.close()
        normalize(reg).to_parquet(out/'strategy_registry.parquet',index=False)
    for period,rows in all_metrics.items():
        folder=out if period=='FULL_HISTORY' else out/'common_period'
        df=normalize(pd.DataFrame(rows));df.to_parquet(folder/'strategy_metrics.parquet',index=False)
        cube=df.merge(reg[['strategy_id','selection_method','target_delta','target_otm','target_dte','roll_dte','coverage_ratio']],on='strategy_id',validate='many_to_one')
        cube.to_parquet(folder/'strategy_parameter_cube.parquet',index=False)
    last=normalize(pd.concat(latest,ignore_index=True));last.to_parquet(out/'strategy_latest_state_scenarios.parquet',index=False)
    last.loc[last.scenario_id.eq('BASE')].to_parquet(out/'strategy_latest_state.parquet',index=False)
    normalize(pd.DataFrame(audit_rows)).to_parquet(out/'strategy_audit.parquet',index=False)
    normalize(pd.DataFrame(hash_rows)).to_parquet(out/'strategy_result_hashes.parquet',index=False)
    # 确定性随机抽样只用于人工审计，不使用收益挑选模块。
    sample=reg.groupby('selection_method',group_keys=False).sample(n=10,random_state=20260828)
    sample.merge(pd.DataFrame(all_metrics['FULL_HISTORY']).query("scenario_id=='BASE'"),on='strategy_id',suffixes=('','_metric')).to_parquet(out/'strategy_sample_audit.parquet',index=False)
    json_write(dict(run_id=run_id,status='COMPUTED_PENDING_FINAL_AUDIT',output=str(out),full_counts=full.counts,
                    common_counts=common_writer.counts,elapsed_seconds=time.perf_counter()-timing),out/'run_status.json')
    json_write(dict(run_id=run_id,output=str(out),status='COMPUTED_PENDING_FINAL_AUDIT'),ROOT/'outputs'/'strategy_universe'/'latest_run.json')
    print('COMPUTATION COMPLETE',out,flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-only',action='store_true')
    args=parser.parse_args();main(args.baseline_only)
