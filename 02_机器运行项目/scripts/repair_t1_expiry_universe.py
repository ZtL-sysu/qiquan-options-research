"""可追溯的T+1合约有效期修复：重算所有可能受影响的结构，流式合并其余已审计结果。

只按规则差异识别影响范围，不根据绩效挑选重算对象；完成后仍须独立复跑全部576模块。
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse,hashlib,json,shutil,time,zipfile
from datetime import datetime
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from covered_call.data import ROOT,json_write
from covered_call.margin_engine import PreparedMarket,run_margin_backtest
from covered_call.universe_config import registry,SCENARIOS,DEFAULTS,PARAMETER_VERSION,ENGINE_VERSION
from covered_call.universe_analytics import audit_frames,add_benchmark,metrics,regime_metrics,market_states
from covered_call.universe_io import LongTables,attach_metadata,normalize,EVENT_COLUMNS
from verify_strategy_universe import load_snapshot
from run_strategy_universe import digest_frames


def repair(old):
    old=Path(old).resolve();old_manifest=json.loads((old/'run_manifest.json').read_text(encoding='utf-8'))
    out=ROOT/'outputs/strategy_universe'/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_t1expiry');out.mkdir()
    shutil.copytree(old/'data_snapshot',out/'data_snapshot')
    shutil.copy2(old/'delta_quality_daily.parquet',out/'delta_quality_daily.parquet')
    manifest={**old_manifest,'run_id':out.name,'parameter_version':PARAMETER_VERSION,'defaults':DEFAULTS,
              'supersedes':str(old),'repair':'At T exclude expiry<=known next trading date; never read T+1 prices for selection.'}
    manifest['rule_notes']['tie_break']='eligible calendar DTE7..90 AND expiry>known T+1; closest target DTE then earlier expiry; closest target then strike/code'
    files=sorted([*ROOT.glob('covered_call/*.py'),*ROOT.glob('scripts/*.py'),*ROOT.glob('tests/*.py'),*ROOT.glob('data_audit/*.py'),*ROOT.glob('config/*.yaml')])
    code_hash=hashlib.sha256(b''.join(str(p.relative_to(ROOT)).encode()+p.read_bytes() for p in files)).hexdigest()
    manifest['code_sha256']=code_hash;manifest['engine_version']=ENGINE_VERSION+'_'+code_hash[:12]
    with zipfile.ZipFile(out/'source_code_snapshot.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,p.relative_to(ROOT))
    json_write(manifest,out/'run_manifest.json');json_write(dict(status='REPAIR_RUNNING'),out/'run_status.json')
    print('REPAIR OUTPUT',out,flush=True)
    market=load_snapshot(out/'data_snapshot');prepared=PreparedMarket(market)
    reg=registry();old_reg=pd.read_parquet(old/'strategy_registry.parquet')
    for col in ['data_start_date','effective_start_date','latest_date','status','failure_reason']:
        reg[col]=reg.strategy_id.map(old_reg.set_index('strategy_id')[col])
    combinations=reg.drop_duplicates(['selection_method','target_delta','target_otm','target_dte'])
    changed=[];keys=set()
    for date,expiries in prepared.eligible.items():
        tomorrow=prepared.calendar[prepared.calendar.searchsorted(date,side='right')]
        if not any(7<=(expiry-date).days<=90 and expiry<=tomorrow for expiry in expiries): continue
        for param in combinations.to_dict('records'):
            before,_=prepared.select(date,param,dict(DEFAULTS,require_valid_t1=False));after,_=prepared.select(date,param,DEFAULTS)
            a=before['option_code'] if before else None;b=after['option_code'] if after else None
            if a!=b:
                target=param['target_delta'] if param['selection_method']=='DELTA' else param['target_otm']
                keys.add((param['selection_method'],target,param['target_dte']))
                changed.append(dict(date=date,next_trading_date=tomorrow,selection_method=param['selection_method'],target=target,
                    target_dte=param['target_dte'],old_option=a,new_option=b,old_expiry=before['expiry'] if before else pd.NaT,
                    new_expiry=after['expiry'] if after else pd.NaT))
    affected=[r for r in reg.to_dict('records') if (r['selection_method'],r['target_delta'] if r['selection_method']=='DELTA' else r['target_otm'],r['target_dte']) in keys]
    ids={r['strategy_id'] for r in affected};pd.DataFrame(changed).to_parquet(out/'t1_expiry_selection_changes.parquet',index=False)
    json_write(dict(affected_modules=len(ids),affected_ids=sorted(ids),comparison_source=str(old),selection_changes=len(changed)),out/'repair_scope.json')
    print('Affected structural modules',len(ids),'selection changes',len(changed),flush=True)
    base_meta={k:manifest[k] for k in ['run_id','parameter_version','data_version','source_hash','engine_version']}
    start=pd.Timestamp(manifest['full_history_start']);common=pd.Timestamp(manifest['common_period_start']);end=pd.Timestamp(manifest['end_date'])
    # 新版先重新验证四条基线。
    baseline=[];bw=LongTables(out/'baseline')
    for method in ['MONEYNESS','DELTA']:
        param=dict(strategy_id='BASELINE_'+method,selection_method=method,target_delta=.25,target_otm=.05,target_dte=35,roll_dte=2,coverage_ratio=1.)
        for sid,scenario in SCENARIOS.items():
            f,s=run_margin_backtest(prepared,param,start if method=='MONEYNESS' else common,end,scenario,dict(min_dte=25,max_dte=45))
            checks=audit_frames(f,prepared,param)
            if not s['completed']: raise AssertionError('新版baseline失败')
            for k in ['daily','trades','rolls','ledger']: bw.append(k,attach_metadata(f[k],dict(strategy_id=param['strategy_id'],scenario_id=sid)))
            baseline.append(dict(strategy_id=param['strategy_id'],scenario_id=sid,**s,final_NAV=float(f['daily'].NAV.iloc[-1]),
                                 maximum_financing=float(f['daily'].financing_balance.max()),audit=checks))
    bw.close();json_write(baseline,out/'baseline_validation.json')
    states=market_states(market,prepared)
    pd.testing.assert_frame_equal(states,pd.read_parquet(old/'market_state_daily.parquet'))
    states.to_parquet(out/'market_state_daily.parquet',index=False)
    bench=pd.read_parquet(old/'benchmark_daily.parquet');bench=attach_metadata(bench,base_meta)
    bench.to_parquet(out/'benchmark_daily.parquet',index=False)
    benchmarks={k:g for k,g in bench.groupby('period_id')}
    writers={period:LongTables(out/'recomputed'/period) for period in ['FULL_HISTORY','COMMON_PERIOD']}
    metrics_rows={p:[] for p in writers};latest=[];audits=[];hashes=[];clock=time.perf_counter()
    names=dict(daily='strategy_daily',trades='strategy_trades',rolls='strategy_rolls',ledger='strategy_cash_ledger',events='strategy_events')
    for i,param in enumerate(affected):
        failures=[]
        for sid,scenario in SCENARIOS.items():
            for period in writers:
                if period=='FULL_HISTORY' or param['selection_method']=='MONEYNESS':
                    begin=common if period=='COMMON_PERIOD' or param['selection_method']=='DELTA' else start
                    f,s=run_margin_backtest(prepared,param,begin,end,scenario)
                    checks=audit_frames(f,prepared,param);digest=digest_frames(f)
                if not s['completed']: failures.append(sid+' '+period+':'+s['failure_reason'])
                meta=dict(strategy_id=param['strategy_id'],scenario_id=sid,period_id=period,**base_meta)
                df=add_benchmark(f['daily'],benchmarks['COMMON_PERIOD' if param['selection_method']=='DELTA' else period])
                for key,name in names.items():
                    frame=df if key=='daily' else f[key]
                    if key=='events': frame=frame.reindex(columns=EVENT_COLUMNS)
                    writers[period].append(name,attach_metadata(frame,meta))
                writers[period].append('strategy_regime_metrics',attach_metadata(regime_metrics(df,states),meta))
                metrics_rows[period].append(dict(**metrics({**f,'daily':df},s),**meta))
                audits.append(dict(**meta,**checks,completed=s['completed'],failure_reason=s['failure_reason']))
                hashes.append(dict(**meta,content_sha256=digest))
                if period=='FULL_HISTORY':
                    last=df.iloc[[-1]].copy();last['failure_reason']=s['failure_reason'];last['latest_date']=end;last['is_current']=last.date.eq(end)
                    if not s['completed']: last['strategy_state']='STOPPED';last['next_action']='STOPPED'
                    last['current_option']=last.short_call_code;last['DTE']=last.calendar_DTE
                    last['premium_received']=last.premium_received_cumulative;last['unrealized_option_pnl']=last.option_unrealized_pnl
                    latest.append(attach_metadata(last,meta))
        reg.loc[reg.strategy_id.eq(param['strategy_id']),'status']='STOPPED' if failures else 'COMPLETED'
        reg.loc[reg.strategy_id.eq(param['strategy_id']),'failure_reason']=';'.join(failures)
        if (i+1)%24==0: print(f'Repaired {i+1}/{len(affected)} modules; {time.perf_counter()-clock:.1f}s',flush=True)
    for writer in writers.values(): writer.close()
    # 用旧结果中的未受影响模块加新版完整重算模块，合并为统一长表；不留下重复主键。
    counts={}
    for period in writers:
        folder=out if period=='FULL_HISTORY' else out/'common_period';src=old if period=='FULL_HISTORY' else old/'common_period'
        merged=LongTables(folder)
        for name in [*names.values(),'strategy_regime_metrics']:
            for file,filter_old in [(src/(name+'.parquet'),True),(out/'recomputed'/period/(name+'.parquet'),False)]:
                if not file.exists(): continue
                for batch in pq.ParquetFile(file).iter_batches(batch_size=10000):
                    frame=batch.to_pandas()
                    if filter_old: frame=frame.loc[~frame.strategy_id.isin(ids)]
                    merged.append(name,attach_metadata(frame,base_meta))
        merged.close();counts[period]=merged.counts
        old_metrics=pd.read_parquet(src/'strategy_metrics.parquet');old_metrics=old_metrics.loc[~old_metrics.strategy_id.isin(ids)]
        met=normalize(pd.concat([attach_metadata(old_metrics,base_meta),pd.DataFrame(metrics_rows[period])],ignore_index=True))
        met.to_parquet(folder/'strategy_metrics.parquet',index=False)
        met.merge(reg[['strategy_id','selection_method','target_delta','target_otm','target_dte','roll_dte','coverage_ratio']],on='strategy_id',validate='many_to_one').to_parquet(folder/'strategy_parameter_cube.parquet',index=False)
    def combine(name,new):
        previous=pd.read_parquet(old/(name+'.parquet'));previous=previous.loc[~previous.strategy_id.isin(ids)]
        result=normalize(pd.concat([attach_metadata(previous,base_meta),new],ignore_index=True))
        result.to_parquet(out/(name+'.parquet'),index=False);return result
    last=combine('strategy_latest_state_scenarios',pd.concat(latest,ignore_index=True))
    last.loc[last.scenario_id.eq('BASE')].to_parquet(out/'strategy_latest_state.parquet',index=False)
    combine('strategy_audit',pd.DataFrame(audits));combine('strategy_result_hashes',pd.DataFrame(hashes))
    normalize(reg).to_parquet(out/'strategy_registry.parquet',index=False)
    sample=reg.groupby('selection_method',group_keys=False).sample(n=10,random_state=20260828)
    met=pd.read_parquet(out/'strategy_metrics.parquet')
    sample.merge(met.loc[met.scenario_id.eq('BASE')],on='strategy_id',suffixes=('','_metric')).to_parquet(out/'strategy_sample_audit.parquet',index=False)
    json_write(dict(run_id=out.name,status='COMPUTED_PENDING_FINAL_AUDIT',output=str(out),
        full_counts=counts['FULL_HISTORY'],common_counts=counts['COMMON_PERIOD'],recomputed_modules=len(ids),elapsed_seconds=time.perf_counter()-clock),out/'run_status.json')
    json_write(dict(run_id=out.name,output=str(out),status='COMPUTED_PENDING_FINAL_AUDIT'),ROOT/'outputs/strategy_universe/latest_run.json')
    print('REPAIR COMPUTATION COMPLETE',out,flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--old',required=True);repair(parser.parse_args().old)
