"""事后分析；本文件任何市场状态与绩效均不作为交易输入。"""
import numpy as np
import pandas as pd
from .selection import mark_price


def reliable_delta_history(market, threshold=.95, consecutive=60):
    o=market['options'];dte=(o.expiry-o.date).dt.days
    live=o.loc[o.call_put.eq('C') & ~o.adjusted_contract_flag & o.volume.gt(0) &
               o.open_interest.gt(0) & o.close.gt(0) & dte.between(7,90)].copy()
    live['valid_delta']=live.delta_wind.between(0,1)
    profile=live.groupby('date').valid_delta.agg(valid_count='sum',eligible_count='count',coverage='mean')
    dates=pd.DatetimeIndex(market['underlying'].date).sort_values()
    profile=profile.reindex(dates).fillna(0)
    ok=profile.coverage.ge(threshold)
    runs=ok.rolling(consecutive,min_periods=consecutive).sum().eq(consecutive)
    if not runs.any(): raise ValueError('未发现连续60日可靠Wind Delta区间')
    confirmed=profile.index[runs][0];start=profile.index[profile.index.get_loc(confirmed)-consecutive+1]
    profile['reliable_day']=ok
    return start,profile.rename_axis('date').reset_index(),dict(threshold=threshold,consecutive=consecutive,
        delta_reliable_start_date=str(start.date()),quality_confirmation_date=str(confirmed.date()),
        caveat='事后数据可用性界定；确认日早于此无法据此声称当时已证实连续覆盖。非收益择时条件。')


def market_states(market, prepared):
    u=market['underlying'].sort_values('date').set_index('date')
    div=market['dividends'].set_index('date').dividend_per_share.reindex(u.index,fill_value=0)
    ret=(u.close+div)/u.close.shift(1)-1
    tr=(1+ret.fillna(0)).cumprod()
    out=pd.DataFrame(index=u.index)
    for n in [1,5,20,60]: out[f'ETF_return_{n}d']=tr.pct_change(n,fill_method=None)
    for n in [20,60]:
        out[f'ETF_vol_{n}d']=ret.rolling(n,min_periods=n).std(ddof=1)*np.sqrt(252)
        out[f'RV{n}']=out[f'ETF_vol_{n}d']
        out[f'MA{n}']=u.close.rolling(n,min_periods=n).mean()
        out[f'price_vs_MA{n}']=u.close/out[f'MA{n}']-1
    out['ETF_drawdown']=tr/tr.cummax()-1
    atm,delta=[],[]
    cfg=dict(min_dte=7,max_dte=90)
    for date in out.index:
        a,_=prepared.select(date,dict(selection_method='MONEYNESS',target_otm=0.,target_dte=30),cfg)
        d,_=prepared.select(date,dict(selection_method='DELTA',target_delta=.25,target_dte=30),cfg)
        atm.append(a.get('iv_wind',np.nan) if a else np.nan)
        delta.append(d.get('iv_wind',np.nan) if d else np.nan)
    out['IV_ATM']=atm;out['IV_25D_Call']=delta
    out.loc[out.IV_ATM.le(0),'IV_ATM']=np.nan;out.loc[out.IV_25D_Call.le(0),'IV_25D_Call']=np.nan
    out['IV_percentile_1y']=out.IV_ATM.rolling(252,min_periods=252).rank(pct=True)
    out['IV_minus_RV20']=out.IV_ATM-out.RV20
    out['call_skew']=out.IV_25D_Call-out.IV_ATM
    out['trend_regime']='SIDEWAYS'
    out.loc[(out.price_vs_MA60>.02)&(out.MA20>out.MA60),'trend_regime']='TREND_UP'
    out.loc[(out.price_vs_MA60<-.02)&(out.MA20<out.MA60),'trend_regime']='TREND_DOWN'
    out.loc[out.MA60.isna(),'trend_regime']='UNKNOWN'
    out['vol_regime']=np.select([out.RV20<.15,out.RV20>.25],['VOL_LOW','VOL_HIGH'],default='VOL_MID')
    out.loc[out.RV20.isna(),'vol_regime']='UNKNOWN'
    out['iv_regime']=np.select([out.IV_percentile_1y<=.3,out.IV_percentile_1y>=.7],['IV_LOW','IV_HIGH'],default='IV_MID')
    out.loc[out.IV_percentile_1y.isna(),'iv_regime']='UNKNOWN'
    return out.rename_axis('date').reset_index()


def add_benchmark(daily, benchmark, initial=1e6):
    d=daily.copy();b=benchmark.set_index('date').NAV
    d['benchmark_NAV']=d.date.map(b)
    if d.benchmark_NAV.isna().any(): raise AssertionError('基准日期缺口')
    d['benchmark_daily_return']=d.benchmark_NAV.pct_change(fill_method=None).fillna(d.benchmark_NAV.iloc[0]/initial-1)
    d['excess_NAV']=d.NAV/d.benchmark_NAV
    d['excess_return_arithmetic']=(d.NAV-d.benchmark_NAV)/initial
    for months in [3,6,12,24]:
        # 日历月窗口，端点使用不晚于回溯日期的最近交易日，禁止向后找未来日期。
        dates=pd.DatetimeIndex(d.date);cutoff=dates-pd.DateOffset(months=months)
        index=dates.searchsorted(cutoff,side='right')-1
        valid=index>=0;values=np.full(len(d),np.nan)
        n=d.NAV.to_numpy();v=d.benchmark_NAV.to_numpy()
        values[valid]=n[valid]/n[index[valid]]-v[valid]/v[index[valid]]
        d[f'rolling_excess_{months}M']=values
    return d


def safe_ratio(a,b):
    return float(a/b) if np.isfinite(a) and np.isfinite(b) and abs(b)>1e-15 else np.nan


def metrics(frames, status, initial=1e6):
    d=frames['daily'];t=frames['trades'];r=frames['rolls']
    returns=d.daily_return;years=(d.date.iloc[-1]-d.date.iloc[0]).days/365.25
    cagr=(d.NAV.iloc[-1]/initial)**(1/years)-1 if years>0 and d.NAV.iloc[-1]>0 else np.nan
    vol=returns.std(ddof=1)*np.sqrt(252);dd=d.drawdown.min()
    downside=np.sqrt(np.mean(np.minimum(returns,0)**2))*np.sqrt(252)
    monthly=d.set_index('date')[['NAV','benchmark_NAV']].resample('ME').last()
    monthly=monthly/monthly.shift(1).fillna(initial)-1
    up=monthly[monthly.benchmark_NAV>0];down=monthly[monthly.benchmark_NAV<0]
    entry=t.loc[t.side.eq('SELL_TO_OPEN')] if len(t) else t
    option=t.loc[t.instrument.eq('OPTION')] if len(t) else t
    atomic=r.loc[r.status.eq('ATOMIC')] if len(r) else r
    debit=-atomic.net_roll_cashflow.clip(upper=0) if len(atomic) else pd.Series(dtype=float)
    result=dict(start_date=d.date.iloc[0],end_date=d.date.iloc[-1],status='COMPLETED' if status['completed'] else 'STOPPED',
        failure_reason=status['failure_reason'],CAGR=cagr,Annualized_Volatility=vol,
        Sharpe=safe_ratio(returns.mean()*252,vol),Sortino=safe_ratio(returns.mean()*252,downside),
        Max_Drawdown=dd,Calmar=safe_ratio(cagr,abs(dd)),Upside_Capture=safe_ratio(up.NAV.mean(),up.benchmark_NAV.mean()),
        Downside_Capture=safe_ratio(down.NAV.mean(),down.benchmark_NAV.mean()),
        Annualized_Premium_Yield=safe_ratio(d.premium_income.sum()/initial,years),
        Option_Net_PnL=d.option_net_pnl.sum(),Option_PnL_Initial_NAV=d.option_net_pnl.sum()/initial,
        Total_Premium_Received=d.premium_income.sum(),Transaction_Cost=d.transaction_cost.sum(),
        Financing_Interest=d.financing_interest.sum(),Average_Coverage=d.coverage_ratio.mean(),
        Percentage_Days_Covered=d.short_call_contracts.gt(0).mean(),Number_Trades=len(option),Number_Rolls=len(atomic),
        Debit_Roll_Ratio=debit.gt(0).mean() if len(debit) else np.nan,
        Average_Roll_Debit=debit[debit>0].mean() if debit.gt(0).any() else 0.,Maximum_Roll_Debit=debit.max() if len(debit) else 0.,
        Maximum_Financing=d.financing_balance.max(),Maximum_Financing_NAV=(d.financing_balance/d.NAV).max(),
        net_return=d.NAV.iloc[-1]/initial-1,final_NAV=d.NAV.iloc[-1],minimum_NAV=d.NAV.min(),
        minimum_cash=d.cash.min(),negative_NAV_days=d.NAV.le(0).sum(),
        naked_exposure_days=d.naked_exposure.sum(),over_target_coverage_days=d.over_target_coverage.sum(),
        missing_signal_days=d.event_flags.str.contains('MISSING_SIGNAL',regex=False).sum(),
        no_eligible_days=d.event_flags.str.contains('NO_ELIGIBLE_OPTION',regex=False).sum(),
        same_contract_rolls=atomic.same_contract.sum() if len(atomic) else 0,
        risk_close_only_count=r.status.eq('EXPIRY_RISK_CLOSE_ONLY').sum() if len(r) else 0,
        first_trade_date=option.execution_date.min() if len(option) else pd.NaT,
        latest_trade_date=option.execution_date.max() if len(option) else pd.NaT,
        max_abs_daily_return=d.daily_return.abs().max(),benchmark_net_return=d.benchmark_NAV.iloc[-1]/initial-1,
        pnl_reconciliation_max_abs=d.pnl_reconciliation_error.abs().max(),daily_rows=len(d))
    for out,col in [('Average_Entry_Delta','entry_delta'),('Average_Entry_Moneyness','moneyness'),('Average_Entry_DTE','DTE'),('Average_Entry_IV','entry_IV')]:
        result[out]=entry[col].mean() if len(entry) else np.nan
    return result


def regime_metrics(daily, states):
    d=daily.merge(states[['date','trend_regime','vol_regime','iv_regime']],on='date',validate='one_to_one')
    rows=[]
    for dimension in ['trend','vol','iv']:
        for value,g in d.groupby(dimension+'_regime',sort=True):
            ret=g.daily_return;vol=ret.std(ddof=1)*np.sqrt(252)
            nav=(1+ret).cumprod();dd=nav/nav.cummax().clip(lower=1)-1
            up=g[g.benchmark_daily_return>0];down=g[g.benchmark_daily_return<0]
            rows.append(dict(regime_dimension=dimension,regime_value=value,number_of_days=len(g),
                annualized_return=nav.iloc[-1]**(252/len(g))-1 if nav.iloc[-1]>0 else np.nan,
                volatility=vol,Sharpe=safe_ratio(ret.mean()*252,vol),max_drawdown=dd.min(),
                average_daily_return=ret.mean(),win_rate=ret.gt(0).mean(),option_pnl=g.option_net_pnl.sum(),
                premium_income=g.premium_income.sum(),upside_capture=safe_ratio(up.daily_return.mean(),up.benchmark_daily_return.mean()),
                downside_capture=safe_ratio(down.daily_return.mean(),down.benchmark_daily_return.mean())))
    return pd.DataFrame(rows)


def audit_frames(frames, prepared, params):
    """独立从导出账本和成交重建现金、融资、持仓、成本，再核对真实行情来源。"""
    d=frames['daily'].set_index('date');l=frames['ledger'];t=frames['trades'];r=frames['rolls']
    errors={}
    cash=l.groupby('date').amount.sum().reindex(d.index,fill_value=0).cumsum()
    debt=l.groupby('date').debt_change.sum().reindex(d.index,fill_value=0).cumsum()
    errors['cash']=float((cash-d.cash).abs().max());errors['financing']=float((debt-d.financing_balance).abs().max())
    errors['NAV']=float((cash+d.ETF_market_value+d.option_market_value-debt-d.NAV).abs().max())
    option=t.loc[t.instrument.eq('OPTION')].copy() if len(t) else t
    if len(t):
        etf=t[t.instrument.eq('ETF')]
        shares=etf.groupby('execution_date').shares.sum().reindex(d.index,fill_value=0).cumsum()
        errors['ETF_shares']=float((shares-d.ETF_shares).abs().max())
        tc=t.groupby('execution_date')[['commission','slippage']].sum().sum(axis=1).reindex(d.index,fill_value=0)
        errors['cost']=float((tc-d.transaction_cost).abs().max())
    if len(option):
        option['signed_quantity']=np.where(option.side.eq('SELL_TO_OPEN'),option.contracts,-option.contracts)
        qty=option.groupby('execution_date').signed_quantity.sum().reindex(d.index,fill_value=0).cumsum()
        errors['contracts']=float((qty-d.short_call_contracts).abs().max())
        flow=option.groupby('execution_date').gross_cashflow.sum().reindex(d.index,fill_value=0)
        pnl=d.option_market_value.diff().fillna(d.option_market_value.iloc[0])+flow
        errors['option_pnl']=float((pnl-d.option_pnl).abs().max())
        for trade in option.to_dict('records'):
            expected=prepared.calendar[prepared.calendar.searchsorted(trade['signal_date'],side='right')]
            if trade['execution_date']!=expected: raise AssertionError('非T+1')
            row=prepared.days[trade['execution_date']][trade['option_code']]
            sig=prepared.days[trade['signal_date']][trade['option_code']]
            if not np.allclose([trade['market_price'],trade['strike'],trade['contract_multiplier']],
                               [row['close'],row['strike'],row['contract_multiplier']],rtol=0,atol=1e-10):
                raise AssertionError('成交条款/价格非真实当日来源')
            if trade['side']=='SELL_TO_OPEN':
                if not np.allclose([trade['signal_delta'],trade['signal_strike']],[sig.get('delta_wind',np.nan),sig['strike']],equal_nan=True):
                    raise AssertionError('信号使用非当日Wind数据/条款')
                s=d.loc[trade['execution_date'],'ETF_shares'];q=trade['contracts'];mult=trade['contract_multiplier'];target=params['coverage_ratio']
                if not q*mult<=s*target+1e-8 or (q+1)*mult<=s*target-1e-8: raise AssertionError('开仓非覆盖率下最大整数')
        if len(r):
            if r.signal_old_trading_DTE.gt(params['roll_dte']).any(): raise AssertionError('提前触发Roll')
            for roll in r.to_dict('records'):
                legs=option.loc[option.roll_id.eq(roll['roll_id'])]
                if roll['status']=='ATOMIC' and len(legs)!=2: raise AssertionError('组合不是两条腿')
                if abs(legs.net_cashflow.sum()-roll['net_roll_cashflow'])>1e-6: raise AssertionError('组合净额不平')
    max_mark_error=0.
    for row in d.loc[d.short_call_contracts.gt(0)].reset_index().to_dict('records'):
        source=prepared.days[row['date']][row['short_call_code']];mark,_=mark_price(source)
        max_mark_error=max(max_mark_error,abs(row['option_market_value']+row['short_call_contracts']*source['contract_multiplier']*mark))
    errors['source_mark']=max_mark_error
    if max(errors.values(),default=0)>1e-5: raise AssertionError('独立重算失败 '+str(errors))
    if d.cash.lt(-1e-7).any() or l.cash_balance.lt(-1e-7).any(): raise AssertionError('隐式负现金')
    if not np.isfinite(d.NAV).all(): raise AssertionError('非有限NAV')
    return errors
