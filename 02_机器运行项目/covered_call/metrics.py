"""显式定义绩效指标；权利金总收入不等同于期权净收益。"""
import numpy as np
import pandas as pd


def period_returns(daily, initial, frequency):
    values=daily.set_index('date').NAV.resample(frequency).last().dropna()
    return values/values.shift(1).fillna(initial)-1


def ratio(a,b):
    return float(a/b) if np.isfinite(b) and abs(b)>1e-12 else None


def metrics(frames,benchmark,cfg,status):
    d=frames['daily_nav'];initial=cfg['initial_capital']
    if len(d)<2:
        return {'completed':False,'reason':'有效净值不足'},pd.Series(dtype=float),pd.Series(dtype=float)
    returns=d.daily_return
    years=(d.date.max()-d.date.min()).days/365.25
    cagr=(d.NAV.iloc[-1]/initial)**(1/years)-1 if years>0 and d.NAV.iloc[-1]>0 else None
    std=returns.std(ddof=1)
    rf=(1+cfg['sharpe_risk_free_rate'])**(1/252)-1
    excess=returns-rf
    downside=np.sqrt(np.mean(np.minimum(excess,0)**2))
    month=period_returns(d,initial,'ME');year=period_returns(d,initial,'YE')
    benchmark=benchmark.loc[benchmark.date.between(d.date.min(),d.date.max())]
    bmonth=period_returns(benchmark,initial,'ME')
    joined=pd.concat([month.rename('strategy'),bmonth.rename('benchmark')],axis=1).dropna()
    up=joined.loc[joined.benchmark>0];down=joined.loc[joined.benchmark<0]
    trades=frames['trades']
    option=trades.loc[trades.instrument.eq('OPTION')] if len(trades) else pd.DataFrame()
    entry=option.loc[option.side.eq('SELL_TO_OPEN')] if len(option) else pd.DataFrame()
    exit_=option.loc[option.side.eq('BUY_TO_CLOSE')] if len(option) else pd.DataFrame()
    premium=float((entry.market_close*entry.contracts*entry.contract_multiplier).sum()) if len(entry) else 0.
    option_cost=float((option.slippage+option.commission).sum()) if len(option) else 0.
    option_pnl=float(d.option_PnL.sum())
    e=frames['daily_exposure'];r=frames['roll_events']
    realized_loss=float(-exit_.realized_option_PnL_gross.clip(upper=0).sum()) if len(exit_) else 0.
    result={'completed':status['completed'],'start_date':str(d.date.min().date()),'end_date':str(d.date.max().date()),
        'CAGR':cagr,'Annualized_Volatility':float(std*np.sqrt(252)),'Sharpe':ratio(excess.mean()*np.sqrt(252),std),
        'Sortino':ratio(excess.mean()*np.sqrt(252),downside),'Max_Drawdown':float(d.drawdown.min()),'Calmar':ratio(cagr,abs(d.drawdown.min())) if cagr is not None else None,
        'Upside_Capture':ratio(up.strategy.mean(),up.benchmark.mean()),'Downside_Capture':ratio(down.strategy.mean(),down.benchmark.mean()),
        'capture_definition':'月度收益：基准上涨/下跌月份的策略算术平均收益 / 基准算术平均收益；非日度或几何口径',
        'initial_capital':initial,'final_NAV':float(d.NAV.iloc[-1]),'net_return':float(d.NAV.iloc[-1]/initial-1),
        'gross_return_same_positions':float(d.gross_return_same_positions.iloc[-1]),'total_transaction_costs':float(d.transaction_cost.sum()),
        'total_option_costs':option_cost,'total_option_premium_received':premium,
        'realized_option_PnL_gross':float(d.realized_option_PnL_gross_cumulative.iloc[-1]),'realized_option_PnL_net':float(d.realized_option_PnL_net_cumulative.iloc[-1]),
        'unrealized_option_PnL_gross':float(d.unrealized_option_PnL_gross.iloc[-1]),'option_PnL_gross':option_pnl,'option_PnL_net':option_pnl-option_cost,
        'option_PnL_over_initial':(option_pnl-option_cost)/initial,'premium_yield':premium/initial,
        'premium_yield_definition':'累计卖出毛权利金 / 初始资本；不是净收益率，也不是年化',
        'average_entry_DTE':float(entry.DTE.mean()) if len(entry) else None,'average_entry_moneyness':float(entry.moneyness.mean()) if len(entry) else None,
        'average_entry_Delta':float(entry.delta_wind.mean()) if len(entry) and entry.delta_wind.notna().any() else None,
        'average_entry_IV':float(entry.IV_wind.mean()) if len(entry) and entry.IV_wind.notna().any() else None,
        'number_of_rolls':int(r.status.eq('complete').sum()) if len(r) else 0,'number_of_option_trades':len(option),
        'percentage_of_days_covered':float(e.covered_day.mean()),'average_coverage_ratio':float(e.coverage_ratio.mean()) if e.coverage_ratio.notna().any() else None,
        'undercovered_days':int(e.undercovered.sum()),'negative_cash_days':int(e.negative_cash.sum()),'minimum_cash':float(d.cash.min()),
        'dividend_accrual_total':float(d.dividend_PnL.sum()),'interest_PnL':float(d.interest_PnL.sum()),
        'missed_trade_count':len(frames['missed_trade_log']),'missing_signal_count':len(frames['missing_signal_log']),
        'realized_losing_option_trades_gross_loss':realized_loss,'losing_trade_loss_caveat':'包含标的上涨和波动率变化等影响，不等同于纯粹封顶损失',
        'benchmark_net_return':float(benchmark.NAV.iloc[-1]/initial-1),'excess_return_vs_buy_hold':float((d.NAV.iloc[-1]-benchmark.NAV.iloc[-1])/initial),
        'Annual_Return':{str(i.year):float(v) for i,v in year.items()},'Monthly_Return':{i.strftime('%Y-%m'):float(v) for i,v in month.items()}}
    return result,month,year


def independent_reconciliation(frames,cfg):
    """只从导出的账本、成交与头寸重算现金、数量、NAV和成本。"""
    d=frames['daily_nav'].set_index('date');ledger=frames['cash_ledger']
    cash=ledger.groupby('date').amount.sum().reindex(d.index,fill_value=0).cumsum()
    p=frames['option_positions'].set_index('date')
    mv=(p.option_quantity*p.contract_multiplier*p.mark_price.fillna(0)).reindex(d.index)
    check=pd.DataFrame({'cash_error':cash-d.cash,'NAV_error':cash+d.shares*d.raw_spot+mv-d.NAV,'option_market_value_error':mv-d.option_market_value})
    t=frames['trades'];q=pd.Series(0.,index=d.index);s=pd.Series(0.,index=d.index)
    if len(t):
        for _,r in t.iterrows():
            if r.execution_date<=r.signal_date:
                raise AssertionError('同日成交或未来信号')
            if r.instrument=='ETF':
                s.loc[r.execution_date]+=r.shares
            else:
                if not float(r.contracts).is_integer():
                    raise AssertionError('期权张数非整数')
                q.loc[r.execution_date]+=(-r.contracts if r.side=='SELL_TO_OPEN' else r.contracts)
    check['share_error']=s.cumsum()-d.shares
    check['contract_quantity_error']=q.cumsum()-p.option_quantity
    costs=ledger.loc[ledger.event.str.contains('COMMISSION|SLIPPAGE')].groupby('date').amount.sum()
    check['cost_error']=-costs.reindex(d.index,fill_value=0)-d.transaction_cost
    if len(t):
        trade_cost=(t.slippage+t.commission).groupby(t.execution_date).sum().reindex(d.index,fill_value=0)
        check['trade_vs_ledger_cost_error']=trade_cost-d.transaction_cost
    errors=check.abs().max()
    if errors.gt(1e-5).any():
        raise AssertionError('独立账本重算失败: '+str(errors.to_dict()))
    return check.reset_index()


def source_reconciliation(frames,market):
    """将成交时点、成交基价和持仓盯市重新与标准行情层核对。"""
    from .selection import mark_price
    calendar=pd.DatetimeIndex(market['calendar']).sort_values()
    quotes=market['options'].set_index(['date','option_code'])
    underlying=market['underlying'].set_index('date')
    checked=[]
    for _,trade in frames['trades'].iterrows():
        expected=calendar[calendar.searchsorted(trade.signal_date,side='right')]
        if trade.execution_date!=expected:
            raise AssertionError('成交不是信号下一交易日')
        if trade.instrument=='OPTION':
            raw=quotes.loc[(trade.execution_date,trade.option_code)]
            if not np.allclose([trade.market_close,trade.strike,trade.contract_multiplier], [raw.close,raw.strike,raw.contract_multiplier],atol=1e-10,rtol=0):
                raise AssertionError('成交基价/执行价/乘数与当日真实来源不一致')
            if trade.side=='SELL_TO_OPEN':
                signal=quotes.loc[(trade.signal_date,trade.option_code)]
                if not np.isclose(trade.signal_strike,signal.strike,atol=1e-10,rtol=0):
                    raise AssertionError('信号使用了未来调整后的执行价')
                if not np.isclose(trade.signal_delta_wind,signal.delta_wind,equal_nan=True,atol=1e-10,rtol=0):
                    raise AssertionError('信号Delta不是当日Wind来源')
        else:
            if not np.isclose(trade.market_close,underlying.loc[trade.execution_date,'close']):
                raise AssertionError('ETF成交使用了复权价或其他日期价格')
        checked.append({'record_type':'trade','date':trade.execution_date,'reference':trade.trade_id,'passed':True})
    for _,position in frames['option_positions'].iterrows():
        if position.option_quantity==0:
            continue
        raw=quotes.loc[(position.date,position.option_code)]
        mark,source=mark_price(raw)
        if not np.allclose([position.mark_price,position.strike,position.contract_multiplier],[mark,raw.strike,raw.contract_multiplier],atol=1e-10,rtol=0) or position.mark_source!=source:
            raise AssertionError('持仓估值未使用当日价格与有效条款')
        checked.append({'record_type':'position','date':position.date,'reference':position.option_code,'passed':True})
    return pd.DataFrame(checked,columns=['record_type','date','reference','passed'])
