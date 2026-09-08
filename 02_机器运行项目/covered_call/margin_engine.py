"""M2 原始价格、历史条款、T+1规则上的原子组合/显式融资执行层。

所有策略复用 PreparedMarket。市场环境标签不进入本模块。
现金和融资本金分别记账；组合仅按两腿净现金流借款，不对BTC单腿融资。
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .selection import mark_price, execution_valid
from .universe_config import DEFAULTS


class PreparedMarket:
    def __init__(self, market):
        self.calendar = pd.DatetimeIndex(market['calendar']).sort_values()
        self.underlying = market['underlying'].set_index('date').close.to_dict()
        self.dividends = market['dividends'].set_index('date').dividend_per_share.to_dict()
        self.days = {}
        self.eligible = {}
        self.cache = {}
        # 本阶段只有Call模块。缓存仅保留执行所需字段，避免在Windows上复制全部Put/OHLC/来源文本。
        source=market['options']
        columns=['date','option_code','call_put','expiry','first_trade_date','last_trade_date','volume','open_interest',
                 'close','settle','strike','contract_multiplier','adjusted_contract_flag',
                 'delta_wind','gamma_wind','theta_wind','vega_wind','iv_wind']
        options = source.loc[source.call_put.eq('C'),[c for c in columns if c in source]].copy()
        if options.duplicated(['date','option_code']).any():
            raise ValueError('重复日期/合约')
        if options.expiry.max()>self.calendar.max():
            raise ValueError('交易日历未覆盖到期日')
        options['calendar_DTE']=(options.expiry-options.date).dt.days
        options['trading_DTE']=(self.calendar.searchsorted(options.expiry,side='right')-
                                self.calendar.searchsorted(options.date,side='right'))
        shared_dates={}
        for date, frame in options.groupby('date', sort=True):
            quotes = {}
            expiries = {}
            for row in frame.to_dict('records'):
                row['date']=date
                for field in ['expiry','first_trade_date','last_trade_date']:
                    row[field]=shared_dates.setdefault(row[field],row[field])
                expiry = row['expiry']
                quotes[row['option_code']] = row
                if (row['call_put']=='C' and row['volume']>0 and row['open_interest']>0
                    and row['close']>0 and row['strike']>0 and row['contract_multiplier']>0
                    and row['first_trade_date']<=date<=row['last_trade_date']
                    and not row['adjusted_contract_flag']):
                    expiries.setdefault(expiry,[]).append(row)
            self.days[date] = quotes
            self.eligible[date] = expiries

    def select(self, date, params, cfg):
        method = params['selection_method']
        target = float(params['target_delta'] if method=='DELTA' else params['target_otm'])
        valid_t1=cfg.get('require_valid_t1',True)
        key = (date,method,target,params['target_dte'],cfg['min_dte'],cfg['max_dte'],valid_t1)
        if key in self.cache:
            return self.cache[key]
        spot = self.underlying[date]
        expires = self.eligible.get(date,{})
        candidates = [e for e in expires if cfg['min_dte'] <= (e-date).days <= cfg['max_dte']]
        if valid_t1:
            i=self.calendar.searchsorted(date,side='right')
            if i>=len(self.calendar): raise ValueError('日历缺少T+1，不能确认新仓有效期')
            # 只用已知日历/到期日，不观察T+1价格或成交量。长假可能使7个自然日小于一个交易日间隔。
            candidates=[e for e in candidates if e>self.calendar[i]]
        selected, reason = None, 'no_eligible_expiry'
        if candidates:
            expiry = min(candidates,key=lambda e:(abs((e-date).days-params['target_dte']),e))
            rows = expires[expiry]
            if method == 'DELTA':
                rows = [r for r in rows if 0<=r.get('delta_wind',np.nan)<=1]
                reason = 'missing_signal:wind_delta_in_target_expiry'
            if rows:
                def score(row):
                    distance = abs(row['delta_wind']-target) if method=='DELTA' else abs(row['strike']/spot-1-target)
                    return distance,row['strike'],row['option_code']
                selected = min(rows,key=score)
                reason = 'selected'
        self.cache[key] = selected,reason
        return selected,reason


def run_margin_backtest(prepared, params, start, end, scenario, config=None):
    cfg = {**DEFAULTS, **(config or {}), **scenario}
    dates = prepared.calendar[(prepared.calendar>=pd.Timestamp(start))&(prepared.calendar<=pd.Timestamp(end))]
    if len(dates)==0:
        raise ValueError('回测区间没有交易日')
    initial = cfg['initial_capital']
    cash, financing, shares = initial,0.,0
    position, pending = None,None
    previous_nav,previous_etf,previous_option,high = initial,0.,0.,initial
    cost_total,option_cost_total,interest_total,premium_total,realized = 0.,0.,0.,0.,0.
    daily,trades,rolls,ledger,events = [],[],[],[],[]
    status = dict(completed=True,failure_reason='',halt_date=None)
    ledger.append(dict(date=dates[0],event='INITIAL_CAPITAL',amount=initial,debt_change=0.,cash_balance=cash,
                       financing_balance=financing,reference='initial'))
    benchmark = params.get('selection_method')=='BUY_HOLD'
    for j,date in enumerate(dates):
        quotes = prepared.days.get(date,{})
        spot = prepared.underlying.get(date,np.nan)
        reason_stop = ''
        if not np.isfinite(spot) or spot<=0:
            reason_stop = 'missing_raw_ETF_close'
        if position:
            held = quotes.get(position['code'])
            if held is None:
                reason_stop = 'missing_held_quote_or_terms'
            else:
                try:
                    mark_price(held)
                except ValueError:
                    reason_stop = 'missing_held_mark_no_forward_fill'
        if reason_stop:
            status.update(completed=False,failure_reason=reason_stop,halt_date=date)
            break
        day_cost,day_option_cost,day_etf_flow,day_option_flow,day_premium,day_interest = 0.,0.,0.,0.,0.,0.
        flags = []

        def flow(amount, debt_change, event, reference):
            nonlocal cash,financing
            cash += float(amount)
            financing += float(debt_change)
            if abs(cash)<1e-9: cash=0.
            if abs(financing)<1e-9: financing=0.
            if cash < -1e-7 or financing < -1e-7:
                raise AssertionError('禁止隐式负现金/负融资')
            ledger.append(dict(date=date,event=event,amount=float(amount),debt_change=float(debt_change),
                               cash_balance=cash,financing_balance=financing,reference=reference))

        def settle(amount, event, reference):
            if cash+amount < 0:
                borrow = -(cash+amount)
                flow(borrow,borrow,'FINANCING_DRAW',reference)
            flow(amount,0.,event,reference)
            repayment = min(cash,financing)
            if repayment>0:
                flow(-repayment,-repayment,'FINANCING_REPAY',reference)

        if j:
            day_interest = financing*cfg['financing_rate']*(date-dates[j-1]).days/365
            if day_interest: settle(-day_interest,'FINANCING_INTEREST','interest')
        dividend_pnl = shares*float(prepared.dividends.get(date,0.))
        if dividend_pnl:
            settle(dividend_pnl,'DIVIDEND_ECONOMIC_ACCRUAL','ex_dividend')
            flags.append('CORPORATE_ACTION')
        if position:
            held = quotes[position['code']]
            if held['contract_multiplier']!=position['multiplier'] or held['strike']!=position['last_strike']:
                events.append(dict(date=date,event='CORPORATE_ACTION',option_code=position['code'],reason='按生效日更新条款；不自动交易ETF',
                    old_multiplier=position['multiplier'],new_multiplier=held['contract_multiplier'],
                    old_strike=position['last_strike'],new_strike=held['strike'],
                    coverage_ratio=position['contracts']*held['contract_multiplier']/shares))
                position['multiplier']=held['contract_multiplier'];position['last_strike']=held['strike']
                flags.append('CORPORATE_ACTION')
        if pending:
            if prepared.calendar[prepared.calendar.searchsorted(pending['signal_date'],side='right')]!=date:
                raise AssertionError('必须在信号下一交易日成交')
            if pending['buy_etf']:
                price = spot*(1+cfg['etf_slippage_rate']);lot=cfg['etf_lot_size']
                quantity = int(cash/(price*(1+cfg['etf_commission_rate']))//lot)*lot
                commission = max(cfg['etf_min_commission'],quantity*price*cfg['etf_commission_rate']) if quantity else 0.
                while quantity*price+commission > cash+1e-8:
                    quantity-=lot
                    commission=max(cfg['etf_min_commission'],quantity*price*cfg['etf_commission_rate']) if quantity else 0.
                gross=-quantity*spot;slip=quantity*(price-spot)
                settle(gross-commission-slip,'ETF_BUY_NET','ETF_INITIAL')
                shares+=quantity;day_etf_flow+=gross;day_cost+=commission+slip
                trades.append(dict(trade_id='ETF_INITIAL',signal_date=pending['signal_date'],execution_date=date,
                    option_code='510050.SH',instrument='ETF',side='BUY_ETF',contracts=0,shares=quantity,
                    strike=np.nan,spot=spot,DTE=np.nan,entry_delta=np.nan,entry_IV=np.nan,moneyness=np.nan,
                    market_price=spot,execution_price=price,gross_cashflow=gross,commission=commission,slippage=slip,
                    net_cashflow=gross-commission-slip,trade_reason='INITIAL_ALLOCATION',roll_id=None,
                    contract_multiplier=1.,expiry=pd.NaT,signal_delta=np.nan,signal_IV=np.nan,
                    signal_strike=np.nan,signal_spot=prepared.underlying[pending['signal_date']],signal_DTE=np.nan,
                    signal_trading_DTE=np.nan,realized_pnl=np.nan))
            selected=pending['selected'];old=position
            old_quote=quotes.get(old['code']) if old else None
            new_quote=quotes.get(selected['option_code']) if selected else None
            close_ok,close_reason = execution_valid(old_quote,date,False) if old else (True,'')
            open_ok,open_reason = execution_valid(new_quote,date,True) if selected else (False,pending['selection_reason'])
            quantity = int(math.floor(shares*params.get('coverage_ratio',0)/new_quote['contract_multiplier'])) if new_quote else 0
            if open_ok and (new_quote['adjusted_contract_flag'] or quantity<=0):
                open_ok=False;open_reason='adjusted_entry_or_insufficient_coverage'
            if open_ok:
                try: mark_price(new_quote)
                except ValueError: open_ok=False;open_reason='missing_new_mark'
            # 选约或执行失败时，两腿均不成交。到期日仍无法组合则按M2风险退出规则仅平旧仓，明确标记例外。
            risk_close = bool(old and date>=old_quote['expiry'] and close_ok and not open_ok)
            execute = bool(close_ok and open_ok and not benchmark)
            if execute or risk_close:
                roll_id=f'R{date:%Y%m%d}' if old else None
                debt_before=financing
                old_gross=(old['contracts']*old_quote['contract_multiplier']*old_quote['close']) if old else 0.
                new_gross=quantity*new_quote['contract_multiplier']*new_quote['close'] if execute else 0.
                old_comm=old['contracts']*cfg['option_commission'] if old else 0.
                new_comm=quantity*cfg['option_commission'] if execute else 0.
                slip=(old_gross+new_gross)*cfg['option_slippage'];comm=old_comm+new_comm
                net=new_gross-old_gross-slip-comm
                settle(net,'ATOMIC_ROLL_NET' if old and execute else ('RISK_CLOSE_NET' if old else 'OPTION_OPEN_NET'),roll_id or 'open')
                day_option_flow+=new_gross-old_gross;day_cost+=slip+comm;day_option_cost+=slip+comm
                premium_total+=new_gross;day_premium+=new_gross
                for side,row,qty,gross in ([('BUY_TO_CLOSE',old_quote,old['contracts'],-old_gross)] if old else []) + (
                    [('SELL_TO_OPEN',new_quote,quantity,new_gross)] if execute else []):
                    tc=qty*cfg['option_commission'];ts=abs(gross)*cfg['option_slippage']
                    pnl=old['entry_gross']+gross if side=='BUY_TO_CLOSE' else np.nan
                    if side=='BUY_TO_CLOSE': realized+=pnl
                    sig=selected if side=='SELL_TO_OPEN' else prepared.days[pending['signal_date']].get(row['option_code'],{})
                    trades.append(dict(trade_id=f'T{len(trades)+1:06d}',signal_date=pending['signal_date'],execution_date=date,
                        option_code=row['option_code'],instrument='OPTION',side=side,contracts=qty,shares=0,
                        strike=row['strike'],spot=spot,DTE=row['calendar_DTE'],entry_delta=row.get('delta_wind',np.nan),
                        entry_IV=row.get('iv_wind',np.nan),moneyness=row['strike']/spot,market_price=row['close'],
                        execution_price=row['close']*(1+cfg['option_slippage']*(1 if side=='BUY_TO_CLOSE' else -1)),
                        gross_cashflow=gross,commission=tc,slippage=ts,net_cashflow=gross-tc-ts,
                        trade_reason='EXPIRY_RISK_CLOSE_ONLY' if risk_close else ('ATOMIC_ROLL' if old else 'OPEN'),roll_id=roll_id,
                        contract_multiplier=row['contract_multiplier'],expiry=row['expiry'],signal_delta=sig.get('delta_wind',np.nan),
                        signal_IV=sig.get('iv_wind',np.nan),signal_strike=sig.get('strike',np.nan),
                        signal_spot=prepared.underlying[pending['signal_date']],signal_DTE=sig.get('calendar_DTE',np.nan),
                        signal_trading_DTE=sig.get('trading_DTE',np.nan),realized_pnl=pnl))
                if old:
                    rolls.append(dict(roll_id=roll_id,signal_date=pending['signal_date'],execution_date=date,
                        old_option=old['code'],new_option=new_quote['option_code'] if execute else None,
                        old_strike=old_quote['strike'],new_strike=new_quote['strike'] if execute else np.nan,
                        old_delta=old_quote.get('delta_wind',np.nan),new_delta=new_quote.get('delta_wind',np.nan) if execute else np.nan,
                        old_DTE=old_quote['calendar_DTE'],new_DTE=new_quote['calendar_DTE'] if execute else np.nan,
                        buyback_cost=old_gross,new_premium=new_gross,gross_roll_cashflow=new_gross-old_gross,
                        commission=comm,slippage=slip,net_roll_cashflow=net,financing_before=debt_before,
                        financing_after=financing,status='ATOMIC' if execute else 'EXPIRY_RISK_CLOSE_ONLY',
                        same_contract=bool(execute and old['code']==new_quote['option_code']),
                        signal_old_trading_DTE=prepared.days[pending['signal_date']][old['code']]['trading_DTE']))
                    flags.append('ROLLED' if execute else 'UNCOVERED')
                position = dict(code=new_quote['option_code'],contracts=quantity,multiplier=new_quote['contract_multiplier'],
                    last_strike=new_quote['strike'],entry_date=date,entry_spot=spot,entry_strike=new_quote['strike'],
                    entry_moneyness=new_quote['strike']/spot,entry_delta=new_quote.get('delta_wind',np.nan),
                    entry_IV=new_quote.get('iv_wind',np.nan),entry_option_price=new_quote['close'],entry_gross=new_gross) if execute else None
            elif not benchmark:
                events.append(dict(date=date,event='EXECUTION_SKIPPED',option_code=selected['option_code'] if selected else None,
                                   reason=close_reason if not close_ok else open_reason))
            pending=None
        quote = quotes[position['code']] if position else None
        option_mv=0.;mark=np.nan;mark_source=None;coverage=0.;unrealized=0.;units=0
        if position:
            mark,mark_source=mark_price(quote)
            units=position['contracts']*quote['contract_multiplier']
            option_mv=-units*mark;unrealized=position['entry_gross']+option_mv;coverage=units/shares
            if date>=quote['expiry']:
                status.update(completed=False,failure_reason='expiry_close_failed_no_assignment_model',halt_date=date)
        etf_mv=shares*spot;nav=cash+etf_mv+option_mv-financing
        etf_pnl=etf_mv-previous_etf+day_etf_flow
        option_pnl=option_mv-previous_option+day_option_flow
        residual=nav-previous_nav-(etf_pnl+option_pnl+dividend_pnl-day_interest-day_cost)
        if abs(residual)>1e-6: raise AssertionError('逐日PnL不平: '+str(residual))
        if not math.isfinite(nav) or nav<=0:
            status.update(completed=False,failure_reason='nonpositive_or_nonfinite_NAV_financing_stopped',halt_date=date)
        cost_total+=day_cost;option_cost_total+=day_option_cost;interest_total+=day_interest;high=max(high,nav)
        signal,next_action,selection_reason='NONE','HOLD',''
        if status['completed']:
            need_roll=bool(position and quote['trading_DTE']<=params.get('roll_dte',0))
            need_open=position is None and not benchmark
            if need_open or need_roll or j==0:
                selected,selection_reason = (None,'benchmark') if benchmark else prepared.select(date,params,cfg)
                signal='ROLL' if need_roll else ('OPEN' if need_open else 'BUY_ETF')
                if selected is None and not benchmark:
                    flags.append('MISSING_SIGNAL' if selection_reason.startswith('missing_signal') else 'NO_ELIGIBLE_OPTION')
                    events.append(dict(date=date,event=flags[-1],option_code=None,reason=selection_reason))
                    next_action='RETRY_SELECTION'
                else:
                    next_action='ATOMIC_ROLL_T1' if need_roll else ('OPEN_T1' if need_open else 'BUY_ETF_T1')
                    if need_roll: flags.append('ROLL_PENDING')
                next_i=prepared.calendar.searchsorted(date,side='right')
                if next_i<len(prepared.calendar):
                    pending=dict(signal_date=date,execution_date=prepared.calendar[next_i],selected=selected,
                                 buy_etf=(j==0),selection_reason=selection_reason)
            if financing>0: flags.append('FINANCING')
        else:
            flags.append('STOPPED');next_action='STOPPED'
        # 主状态+多重事件标签并存，避免融资覆盖掉换月/数据缺失信息。
        priority=['STOPPED','CORPORATE_ACTION','MISSING_SIGNAL','NO_ELIGIBLE_OPTION','ROLLED','ROLL_PENDING','FINANCING']
        state=next((f for f in priority if f in flags),'HOLD' if position else 'UNCOVERED')
        r=dict(date=date,NAV=nav,daily_return=nav/previous_nav-1,cumulative_return=nav/initial-1,drawdown=nav/high-1,
            ETF_price=spot,ETF_shares=shares,ETF_market_value=etf_mv,short_call_code=position['code'] if position else None,
            short_call_contracts=position['contracts'] if position else 0,option_market_value=option_mv,
            strike=quote['strike'] if position else np.nan,expiry=quote['expiry'] if position else pd.NaT,
            calendar_DTE=quote['calendar_DTE'] if position else np.nan,trading_DTE=quote['trading_DTE'] if position else np.nan,
            contract_multiplier=quote['contract_multiplier'] if position else 0.,mark_price=mark,mark_source=mark_source,
            current_moneyness=quote['strike']/spot if position else np.nan,current_delta=quote.get('delta_wind',np.nan) if position else np.nan,
            current_IV=quote.get('iv_wind',np.nan) if position else np.nan,cash=cash,financing_balance=financing,coverage_ratio=coverage,
            net_delta=shares-units*quote.get('delta_wind',np.nan) if position else float(shares),
            net_gamma=-units*quote.get('gamma_wind',np.nan) if position else 0.,
            net_theta=-units*quote.get('theta_wind',np.nan) if position else 0.,
            net_vega=-units*quote.get('vega_wind',np.nan) if position else 0.,option_unrealized_pnl=unrealized,
            option_realized_pnl=realized,premium_received_cumulative=premium_total,transaction_cost_cumulative=cost_total,
            financing_interest_cumulative=interest_total,strategy_state=state,event_flags='|'.join(dict.fromkeys(flags)),
            signal=signal,next_action=next_action,selection_reason=selection_reason,
            ETF_pnl=etf_pnl,option_pnl=option_pnl,option_net_pnl=option_pnl-day_option_cost,dividend_pnl=dividend_pnl,
            transaction_cost=day_cost,option_transaction_cost=day_option_cost,financing_interest=day_interest,
            premium_income=day_premium,pnl_reconciliation_error=residual,
            over_target_coverage=coverage>params.get('coverage_ratio',0)+1e-10,naked_exposure=coverage>1+1e-10)
        for field in ['entry_date','entry_spot','entry_strike','entry_moneyness','entry_delta','entry_IV','entry_option_price']:
            r[field]=position[field] if position else (pd.NaT if field=='entry_date' else np.nan)
        daily.append(r)
        previous_nav,previous_etf,previous_option=nav,etf_mv,option_mv
        if not status['completed']: break
    status['last_valid_date']=daily[-1]['date'] if daily else pd.NaT
    status['requested_start']=dates[0];status['requested_end']=dates[-1]
    return {k:pd.DataFrame(v) for k,v in dict(daily=daily,trades=trades,rolls=rolls,ledger=ledger,events=events).items()},status
