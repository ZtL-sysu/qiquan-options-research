"""独立结构审计和固定快照逐模块复跑；不重新访问MySQL。"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import argparse
import hashlib
import json
import time
import numpy as np
import pandas as pd
import duckdb
from covered_call.data import ROOT,json_write
from covered_call.margin_engine import PreparedMarket,run_margin_backtest
from covered_call.universe_config import SCENARIOS
from covered_call.query import StrategyUniverse
from run_strategy_universe import digest_frames


def load_snapshot(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    for relative,h in manifest['file_sha256'].items():
        if hashlib.sha256((folder/relative).read_bytes()).hexdigest()!=h: raise AssertionError('冻结数据校验失败')
    terms=pd.read_parquet(folder/'options/510050_contract_terms_asof.parquet')
    quotes=pd.read_parquet(folder/'options/510050_option_eod.parquet')
    wind=pd.read_parquet(folder/'options/510050_wind_greeks.parquet').drop(columns='source')
    return dict(options=terms.merge(quotes,on=['date','option_code'],validate='one_to_one').merge(wind,on=['date','option_code'],how='left',validate='one_to_one'),
                underlying=pd.read_parquet(folder/'underlying/510050.parquet'),
                dividends=pd.read_parquet(folder/'corporate_actions/510050_dividends.parquet'),
                calendar=pd.read_parquet(folder/'calendar/sse_calendar.parquet').date)


def verify(run_directory, replay=True):
    out=Path(run_directory);api=StrategyUniverse(out)
    manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
    reg=api.registry;checks={};conn=duckdb.connect()
    def query(sql,path): return conn.execute(sql,[str(path)]).df()
    for period,folder in [('FULL_HISTORY',out),('COMMON_PERIOD',out/'common_period')]:
        daily=folder/'strategy_daily.parquet'
        summary=query('SELECT count(*) AS "rows",count(DISTINCT (strategy_id,scenario_id,date)) unique_rows,count(DISTINCT strategy_id) strategies, min(NAV) min_NAV,min(cash) min_cash,max(financing_balance/NAV) max_financing_NAV FROM read_parquet(?)',daily).iloc[0].to_dict()
        if summary['rows']!=summary['unique_rows'] or summary['strategies']!=576: raise AssertionError('每日主键或模块数量错误')
        groups=query('SELECT strategy_id,scenario_id,min(date) first_date,max(date) last_date,count(*) n FROM read_parquet(?) GROUP BY ALL',daily)
        if len(groups)!=1152: raise AssertionError('策略×情景不完整')
        met=pd.read_parquet(folder/'strategy_metrics.parquet')
        if len(met)!=1152 or met.duplicated(['strategy_id','scenario_id']).any(): raise AssertionError('指标主键错误')
        exported=query('SELECT max(abs(NAV-cash-ETF_market_value-option_market_value+financing_balance)) nav_error, max(abs(ETF_market_value-ETF_shares*ETF_price)) etf_error FROM read_parquet(?)',daily).iloc[0]
        if exported.max()>1e-6: raise AssertionError('最终导出表资金公式不平')
        summary['exported_NAV_formula_error']=float(exported.nav_error)
        sums=query('SELECT strategy_id,scenario_id,arg_max(NAV,date) final_NAV,min(drawdown) Max_Drawdown,sum(transaction_cost) Transaction_Cost,sum(financing_interest) Financing_Interest,sum(option_net_pnl) Option_Net_PnL FROM read_parquet(?) GROUP BY ALL',daily)
        compared=met.merge(sums,on=['strategy_id','scenario_id'],validate='one_to_one',suffixes=('_metric','_daily'))
        metric_error=0.
        for col in ['final_NAV','Max_Drawdown','Transaction_Cost','Financing_Interest','Option_Net_PnL']:
            metric_error=max(metric_error,float((compared[col+'_metric']-compared[col+'_daily']).abs().max()))
        if metric_error>1e-6: raise AssertionError('指标与最终日表不一致')
        summary['exported_metric_reconciliation_error']=metric_error
        group=groups.merge(reg[['strategy_id','effective_start_date','selection_method']],on='strategy_id',validate='many_to_one')
        calendar=pd.read_parquet(out/'data_snapshot/calendar/sse_calendar.parquet').date
        for row in group.to_dict('records'):
            begin=pd.Timestamp(manifest['common_period_start']) if period=='COMMON_PERIOD' else pd.Timestamp(row['effective_start_date'])
            expected=int(calendar.between(begin,manifest['end_date']).sum())
            m=met[(met.strategy_id==row['strategy_id'])&(met.scenario_id==row['scenario_id'])].iloc[0]
            if m.status=='COMPLETED' and (row['n']!=expected or row['first_date']!=begin or row['last_date']!=pd.Timestamp(manifest['end_date'])):
                raise AssertionError('完整状态却存在日期缺口')
            if m.status!='COMPLETED' and not m.failure_reason: raise AssertionError('失败缺少原因')
        summary['completed_runs']=int(met.status.eq('COMPLETED').sum())
        summary['failed_runs']=int(met.status.ne('COMPLETED').sum())
        summary['naked_strategy_days']=int(query('SELECT sum(CAST(naked_exposure AS BIGINT)) n FROM read_parquet(?)',daily).iloc[0,0])
        checks[period]=summary
        # 环境分组必须按每个维度完整覆盖所有日，不因UNKNOWN丢失数据。
        rm=pd.read_parquet(folder/'strategy_regime_metrics.parquet')
        count=rm.groupby(['strategy_id','scenario_id','regime_dimension']).number_of_days.sum().reset_index()
        matched=count.merge(groups[['strategy_id','scenario_id','n']],on=['strategy_id','scenario_id'],validate='many_to_one')
        if not matched.number_of_days.eq(matched.n).all(): raise AssertionError('环境归因丢日期')
    last=pd.read_parquet(out/'strategy_latest_state.parquet');scen=pd.read_parquet(out/'strategy_latest_state_scenarios.parquet')
    if len(last)!=576 or last.strategy_id.nunique()!=576 or len(scen)!=1152: raise AssertionError('最新状态不完整')
    if not scen.date.eq(pd.Timestamp(manifest['end_date'])).all():
        if not scen.loc[~scen.date.eq(pd.Timestamp(manifest['end_date']))].strategy_state.eq('STOPPED').all(): raise AssertionError('旧状态冒充最新')
    sample=pd.read_parquet(out/'strategy_sample_audit.parquet')
    checks['sample_counts']=sample.groupby('selection_method').size().to_dict()
    # API实际调用验证，包含完整注册表反查；共同区间默认防止历史长度混比。
    for row in reg.to_dict('records'):
        p={k:row[k] for k in ['selection_method','target_dte','roll_dte','coverage_ratio']}
        p['target_delta' if p['selection_method']=='DELTA' else 'target_otm']=row['target_delta' if p['selection_method']=='DELTA' else 'target_otm']
        if api.get_strategy(p)['strategy_id']!=row['strategy_id']: raise AssertionError('参数反查错误')
    ids=sample.strategy_id.iloc[[0,-1]].tolist()
    for strategy_id in ids:
        for call in [api.get_nav,api.get_latest_state,api.get_metrics,api.get_trades,api.get_rolls,api.get_regime_metrics]:
            if call(strategy_id).empty: raise AssertionError('API空结果')
        if api.get_day(strategy_id,manifest['end_date']).empty: raise AssertionError('单日查询失败')
    if api.compare_strategies(ids).empty: raise AssertionError('比较接口失败')
    if len(api.get_parameter_slice(selection_method='DELTA',roll_dte=5,coverage_ratio=1.))!=24: raise AssertionError('完整参数面失败')
    checks['api_registry_roundtrip_count']=576
    json_write(checks,out/'validation_summary.json')
    precomputed=out/'replayed_result_hashes.parquet'
    if replay and precomputed.exists():
        repeat=pd.read_parquet(precomputed)
        if not repeat.source_hash.eq(manifest['source_hash']).all() or not repeat.run_id.eq(manifest['run_id']).all():
            raise AssertionError('复跑使用不同数据或批次')
        original=pd.read_parquet(out/'strategy_result_hashes.parquet')
        result=original[['strategy_id','scenario_id','period_id','content_sha256']].rename(columns={'content_sha256':'expected_sha256'}).merge(
            repeat,on=['strategy_id','scenario_id','period_id'],how='outer',validate='one_to_one')
        result['identical']=result.expected_sha256.eq(result.replayed_sha256)
        if len(result)!=2304 or not result.identical.all():
            result.to_parquet(out/'reproduction_mismatch.parquet',index=False)
            raise AssertionError('独立复跑散列不一致，见reproduction_mismatch')
        result.to_parquet(out/'reproduction_audit.parquet',index=False)
        checks.update(reproduced_unique_modules=int(result.strategy_id.nunique()),matched_period_scenario_results=len(result),
                      independent_backtest_reexecutions=int(result.independent_execution.sum()))
        json_write(checks,out/'validation_summary.json')
    elif replay:
        print('冻结数据逐模块复跑开始',flush=True);prepared=PreparedMarket(load_snapshot(out/'data_snapshot'))
        hashes=pd.read_parquet(out/'strategy_result_hashes.parquet');replays=[];start_time=time.perf_counter()
        for idx,param in enumerate(reg.to_dict('records')):
            for scenario_id in SCENARIOS:
                for period in ['FULL_HISTORY','COMMON_PERIOD']:
                    if param['selection_method']=='DELTA' and period=='COMMON_PERIOD':
                        digest=previous_digest
                    else:
                        begin=manifest['common_period_start'] if period=='COMMON_PERIOD' or param['selection_method']=='DELTA' else manifest['full_history_start']
                        f,status=run_margin_backtest(prepared,param,begin,manifest['end_date'],SCENARIOS[scenario_id])
                        digest=digest_frames(f);previous_digest=digest
                    expected=hashes.loc[hashes.strategy_id.eq(param['strategy_id'])&hashes.scenario_id.eq(scenario_id)&hashes.period_id.eq(period),'content_sha256'].iloc[0]
                    same=digest==expected
                    replays.append(dict(strategy_id=param['strategy_id'],scenario_id=scenario_id,period_id=period,
                                        expected_sha256=expected,replayed_sha256=digest,identical=same,
                                        independent_execution=not(param['selection_method']=='DELTA' and period=='COMMON_PERIOD')))
                    if not same: raise AssertionError('确定性复现失败 '+param['strategy_id']+' '+scenario_id+' '+period)
            if (idx+1)%48==0: print(f'复现 {idx+1}/576; {time.perf_counter()-start_time:.1f}s',flush=True)
        pd.DataFrame(replays).to_parquet(out/'reproduction_audit.parquet',index=False)
        checks['reproduced_unique_modules']=576;checks['matched_period_scenario_results']=len(replays)
        checks['independent_backtest_reexecutions']=sum(r['independent_execution'] for r in replays)
        json_write(checks,out/'validation_summary.json')
    conn.close();print('VALIDATION PASSED',json.dumps(checks,ensure_ascii=False),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--run');parser.add_argument('--skip-replay',action='store_true');args=parser.parse_args()
    out=args.run or json.loads((ROOT/'outputs/strategy_universe/latest_run.json').read_text(encoding='utf-8'))['output']
    verify(out,not args.skip_replay)
