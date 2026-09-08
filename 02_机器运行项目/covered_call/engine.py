"""按日事件账本。信号T收盘，执行T+1收盘，结算价优先估值。"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .selection import select_contract, mark_price, execution_valid
# 新阶段入口；旧 strict-cash 入口保留，用于复核 Milestone 2 历史证据。
from .margin_engine import PreparedMarket, run_margin_backtest


def run_backtest(market, strategy, start, end, cfg, option_slippage):
    full_calendar = pd.DatetimeIndex(market['calendar']).sort_values()
    dates = full_calendar[(full_calendar>=pd.Timestamp(start))&(full_calendar<=pd.Timestamp(end))]
    underlying = market['underlying'].set_index('date')
    dividends = market['dividends'].set_index('date').dividend_per_share.to_dict()
    options = market['options']
    day_groups = {date:frame.set_index('option_code',drop=False) for date,frame in options.loc[options.date.between(dates.min(),dates.max())].groupby('date')}
    initial=float(cfg['initial_capital']); cash=initial; shares=0; position=None; pending=None
    previous_nav=initial; previous_etf_mv=0.; previous_option_mv=0.; total_cost=0.; realized_gross=0.; realized_net=0.
    records={name:[] for name in ['daily_nav','trades','option_positions','roll_events','cash_ledger','dividend_ledger','missed_trade_log','missing_signal_log','daily_exposure','signals','corporate_action_log','reconciliation']}
    status={'completed':True,'reason':'','requested_start':str(dates.min().date()),'requested_end':str(dates.max().date())}
    records['cash_ledger'].append({'date':dates[0],'event':'INITIAL_CAPITAL','amount':initial,'balance':cash,'reference':'initial'})
    for j,date in enumerate(dates):
        day=day_groups.get(date,pd.DataFrame())
        # 无法估值或到期未退出时，整天不落账，保留最后一个可复算净值日。
        if position is not None:
            held = day.loc[position['code']].to_dict() if position['code'] in day.index else None
            halt = None
            if held is None:
                halt = '持仓合约缺少当日条款/行情，禁止前向填充'
            elif date >= held['expiry']:
                halt = '到期前未能平仓；停止，不模拟行权或消灭仓位'
            else:
                try:
                    mark_price(held)
                except ValueError:
                    halt = '持仓期权无有效结算价和收盘价，禁止前向填充'
            if halt:
                status.update(completed=False,reason=halt,halt_date=str(date.date()))
                break
        spot=float(underlying.loc[date,'close'])
        if not np.isfinite(spot) or spot<=0:
            raise ValueError('ETF原始收盘价缺失')
        start_cash=cash; day_cost=0.; day_etf_flow=0.; day_option_flow=0.; dividend_pnl=0.; interest_pnl=0.
        start_shares=shares

        def flow(amount,event,reference):
            nonlocal cash
            cash+=float(amount)
            records['cash_ledger'].append({'date':date,'event':event,'amount':float(amount),'balance':cash,'reference':reference})

        def fail(reason):
            status.update(completed=False,reason=reason,halt_date=str(date.date()),last_valid_date=str(dates[j-1].date()) if j else None)

        if j:
            elapsed=(date-dates[j-1]).days
            interest_pnl=(max(cash,0)*cfg['cash_interest_rate'] + min(cash,0)*cfg['financing_rate'])*elapsed/365
            if interest_pnl:
                flow(interest_pnl,'INTEREST','cash_interest')
        dividend=float(dividends.get(date,0.))
        if dividend and shares:
            dividend_pnl=shares*dividend
            flow(dividend_pnl,'DIVIDEND_ECONOMIC_ACCRUAL','ex_dividend')
            records['dividend_ledger'].append({'date':date,'shares_entitled':shares,'dividend_per_share':dividend,'dividend_accrual':dividend_pnl,'actual_payment_date':None,'convention':'经济应计现金等价账户，非实际支付日'})
        if position is not None:
            current=day.loc[position['code']].to_dict() if position['code'] in day.index else None
            if current is not None and (current['contract_multiplier']!=position['last_multiplier'] or current['strike']!=position['last_strike']):
                records['corporate_action_log'].append({'date':date,'option_code':position['code'],'contracts':position['contracts'],'old_multiplier':position['last_multiplier'],'new_multiplier':current['contract_multiplier'],'old_strike':position['last_strike'],'new_strike':current['strike'],'shares':shares,'coverage_ratio':shares/(position['contracts']*current['contract_multiplier'])})
                position['last_multiplier']=current['contract_multiplier'];position['last_strike']=current['strike']
        if pending is not None:
            if pending['execution_date']!=date or pending['signal_date']>=date:
                raise AssertionError('信号与成交时间不满足T+1')
            if pending.get('buy_etf'):
                price=spot*(1+cfg['etf_slippage_rate']);lot=int(cfg['etf_lot_size'])
                quantity=int(cash/(price*(1+cfg['etf_commission_rate']))//lot)*lot
                while quantity>0 and quantity*price+max(cfg['etf_min_commission'],quantity*price*cfg['etf_commission_rate'])>cash+1e-8:
                    quantity-=lot
                commission=max(cfg['etf_min_commission'],quantity*price*cfg['etf_commission_rate']) if quantity else 0
                slip=quantity*(price-spot)
                reference=f'ETF_{date:%Y%m%d}'
                flow(-quantity*spot,'ETF_BUY_GROSS',reference);flow(-commission,'ETF_COMMISSION',reference);flow(-slip,'ETF_SLIPPAGE',reference)
                day_etf_flow-=quantity*spot;day_cost+=commission+slip;shares+=quantity
                records['trades'].append({'trade_id':reference,'signal_date':pending['signal_date'],'execution_date':date,'instrument':'ETF','option_code':'510050.SH','side':'BUY_ETF','contracts':None,'shares':quantity,'spot':spot,'market_close':spot,'execution_price':price,'slippage':slip,'commission':commission,'trade_reason':'initial_allocation'})
            roll_id=pending.get('roll_id');closed=False;opened=False;can_open=True;old_code=position['code'] if position else None
            if pending.get('close_old') and position is not None:
                code=position['code'];quote=day.loc[code].to_dict() if code in day.index else None
                valid,reason=execution_valid(quote,date,False)
                if valid:
                    quantity=position['contracts'];mult=float(quote['contract_multiplier']);close=float(quote['close'])
                    gross=quantity*mult*close;slip=gross*option_slippage;commission=quantity*cfg['option_commission']
                    if cfg['cash_policy']=='stop' and cash<gross+slip+commission-1e-8:
                        valid=False;reason='insufficient_cash_no_implicit_financing'
                if not valid:
                    can_open=False
                    records['missed_trade_log'].append({'signal_date':pending['signal_date'],'execution_date':date,'option_code':code,'side':'BUY_TO_CLOSE','reason':reason,'roll_id':roll_id})
                else:
                    trade_id=f'O{len(records["trades"])+1:05d}'
                    flow(-gross,'OPTION_BUY_GROSS',trade_id);flow(-slip,'OPTION_SLIPPAGE',trade_id);flow(-commission,'OPTION_COMMISSION',trade_id)
                    day_option_flow-=gross;day_cost+=slip+commission
                    pnl=position['entry_gross']-gross;net_pnl=position['entry_net']-gross-slip-commission
                    realized_gross+=pnl;realized_net+=net_pnl
                    records['trades'].append(trade_record(trade_id,pending,date,quote,'BUY_TO_CLOSE',quantity,spot,close*(1+option_slippage),slip,commission,roll_id,position['entry_trade_id'],pnl,net_pnl))
                    position=None;closed=True
            selected=pending.get('selected')
            if can_open and position is None and selected is not None and strategy!='BUY_HOLD':
                code=selected['option_code'];quote=day.loc[code].to_dict() if code in day.index else None
                valid,reason=execution_valid(quote,date,True)
                if valid and cfg.get('exclude_adjusted_new_entries',True) and quote['adjusted_contract_flag']:
                    valid=False;reason='adjusted_between_signal_and_execution'
                if valid:
                    quantity=int(math.floor(shares/quote['contract_multiplier']))
                    if quantity<=0:
                        valid=False;reason='insufficient_coverage'
                    elif cfg['cash_policy']=='stop' and cash+quantity*quote['contract_multiplier']*quote['close']*(1-option_slippage)-quantity*cfg['option_commission']<0:
                        valid=False;reason='insufficient_cash_for_entry_cost'
                if not valid:
                    records['missed_trade_log'].append({'signal_date':pending['signal_date'],'execution_date':date,'option_code':code,'side':'SELL_TO_OPEN','reason':reason,'roll_id':roll_id})
                else:
                    close=float(quote['close']);gross=quantity*float(quote['contract_multiplier'])*close
                    slip=gross*option_slippage;commission=quantity*cfg['option_commission']
                    trade_id=f'O{len(records["trades"])+1:05d}'
                    flow(gross,'OPTION_SELL_GROSS',trade_id);flow(-slip,'OPTION_SLIPPAGE',trade_id);flow(-commission,'OPTION_COMMISSION',trade_id)
                    day_option_flow+=gross;day_cost+=slip+commission
                    position={'code':code,'contracts':quantity,'entry_gross':gross,'entry_net':gross-slip-commission,'entry_trade_id':trade_id,'entry_date':date,'last_multiplier':quote['contract_multiplier'],'last_strike':quote['strike'],'expiry':quote['expiry']}
                    record=trade_record(trade_id,pending,date,quote,'SELL_TO_OPEN',quantity,spot,close*(1-option_slippage),slip,commission,roll_id,None,None,None)
                    record.update(signal_strike=selected['strike'],signal_moneyness=selected['strike']/selected['signal_spot'],signal_delta_wind=selected.get('delta_wind',np.nan),signal_iv_wind=selected.get('iv_wind',np.nan),signal_spot=selected['signal_spot'])
                    records['trades'].append(record);opened=True
            if roll_id:
                records['roll_events'].append({'roll_id':roll_id,'signal_date':pending['signal_date'],'execution_date':date,'old_contract':old_code,'requested_new_contract':selected['option_code'] if selected else None,'new_contract':position['code'] if opened else None,'old_closed':closed,'new_opened':opened,'status':'complete' if closed and opened else ('closed_only' if closed else 'close_failed')})
            pending=None
        option_mv=0.;unrealized_gross=0.;coverage=np.nan;mark=np.nan;mark_source=None;mult=0.
        if position is not None:
            quote=day.loc[position['code']].to_dict() if position['code'] in day.index else None
            if quote is None:
                fail('持仓合约当日缺少条款/行情，禁止前向填充');break
            if date>=quote['expiry']:
                fail('旧Call未能在到期前退出；不模拟行权或凭空消灭仓位');break
            try:
                mark,mark_source=mark_price(quote)
            except ValueError:
                fail('持仓期权无结算价和收盘价，禁止前向填充');break
            mult=float(quote['contract_multiplier']);option_mv=-position['contracts']*mark*mult
            unrealized_gross=position['entry_gross']+option_mv
            coverage=shares/(position['contracts']*mult)
        etf_mv=shares*spot;nav=cash+etf_mv+option_mv
        etf_pnl=etf_mv-previous_etf_mv+day_etf_flow
        option_pnl=option_mv-previous_option_mv+day_option_flow
        daily_pnl=nav-previous_nav
        explained=etf_pnl+option_pnl+dividend_pnl+interest_pnl-day_cost
        if not np.isclose(daily_pnl,explained,atol=1e-6,rtol=0):
            raise AssertionError('每日PnL与资金账本不平')
        total_cost+=day_cost
        records['reconciliation'].append({'date':date,'nav_formula_error':nav-(cash+etf_mv+option_mv),'pnl_decomposition_error':daily_pnl-explained,'start_cash':start_cash,'end_cash':cash})
        records['daily_nav'].append({'date':date,'NAV':nav,'ETF_market_value':etf_mv,'option_market_value':option_mv,'cash':cash,'daily_PnL':daily_pnl,'ETF_PnL':etf_pnl,'option_PnL':option_pnl,'dividend_PnL':dividend_pnl,'interest_PnL':interest_pnl,'transaction_cost':day_cost,'cumulative_cost':total_cost,'gross_NAV_same_positions':nav+total_cost,'gross_return_same_positions':(nav+total_cost)/initial-1,'cumulative_return':nav/initial-1,'shares':shares,'raw_spot':spot,'realized_option_PnL_gross_cumulative':realized_gross,'realized_option_PnL_net_cumulative':realized_net,'unrealized_option_PnL_gross':unrealized_gross})
        records['option_positions'].append({'date':date,'option_code':position['code'] if position else None,'option_quantity':-position['contracts'] if position else 0,'contract_multiplier':mult,'strike':quote['strike'] if position else None,'exchange_code':quote['exchange_code'] if position else None,'mark_price':mark,'mark_source':mark_source,'option_market_value':option_mv,'entry_trade_id':position['entry_trade_id'] if position else None})
        delta=quote.get('delta_wind',np.nan) if position else 0.
        records['daily_exposure'].append({'date':date,'ETF_shares':shares,'short_contracts':position['contracts'] if position else 0,'current_contract_multiplier':mult,'coverage_ratio':coverage,'undercovered':bool(position and coverage<1-1e-10),'covered_day':position is not None,'net_delta_shares':shares-position['contracts']*mult*delta if position else shares,'negative_cash':cash<0,'option_mark_source':mark_source})
        previous_nav=nav;previous_etf_mv=etf_mv;previous_option_mv=option_mv
        if j==len(dates)-1:
            continue
        tomorrow=dates[j+1]
        need_open=position is None and strategy!='BUY_HOLD'
        need_roll=False
        if position is not None:
            # 必须使用包含未来公布交易日的日历，不能将样本尾端当到期日。
            remaining=int(((full_calendar>date)&(full_calendar<=position['expiry'])).sum())
            if full_calendar.max()<position['expiry']:
                raise ValueError('日历未覆盖合约到期日')
            need_roll=remaining<=cfg['roll_execution_days_before_expiry']+1
        buy_etf=(j==0 and shares==0)
        if need_open or need_roll or buy_etf:
            selected=None;reason='benchmark'
            if strategy!='BUY_HOLD':
                selected,reason=select_contract(day.reset_index(drop=True) if not day.empty else options.iloc[0:0],date,spot,strategy,cfg)
                if selected is None:
                    records['missing_signal_log'].append({'signal_date':date,'planned_execution_date':tomorrow,'reason':reason,'strategy':strategy})
            records['signals'].append({'signal_date':date,'execution_date':tomorrow,'option_code':selected['option_code'] if selected else None,'reason':reason,'action':'roll' if need_roll else ('open' if need_open else 'initial_etf'),'signal_spot':spot})
            if selected is not None or need_roll or buy_etf:
                pending={'signal_date':date,'execution_date':tomorrow,'selected':selected,'close_old':need_roll,'buy_etf':buy_etf,'reason':'roll' if need_roll else 'initial_or_reentry','roll_id':f'R{date:%Y%m%d}' if need_roll else None}
    frames={name:pd.DataFrame(rows) for name,rows in records.items()}
    if not frames['daily_nav'].empty:
        nav=frames['daily_nav']
        nav['drawdown']=nav.NAV/nav.NAV.cummax().clip(lower=initial)-1
        nav['daily_return']=nav.NAV.div(nav.NAV.shift(1).fillna(initial))-1
    status['negative_cash_ever']=bool(any(r['negative_cash'] for r in records['daily_exposure']))
    status['last_valid_date']=str(frames['daily_nav'].date.max().date()) if len(frames['daily_nav']) else None
    return frames,status


def trade_record(trade_id,pending,date,quote,side,quantity,spot,execution,slip,commission,roll_id,entry_id,realized,realized_net):
    return {'trade_id':trade_id,'signal_date':pending['signal_date'],'execution_date':date,'instrument':'OPTION','option_code':quote['option_code'],'side':side,'contracts':int(quantity),'strike':quote['strike'],'contract_multiplier':quote['contract_multiplier'],'DTE':(quote['expiry']-date).days,'expiry':quote['expiry'],'spot':spot,'moneyness':quote['strike']/spot,'delta_wind':quote.get('delta_wind',np.nan),'IV_wind':quote.get('iv_wind',np.nan),'market_close':quote['close'],'execution_price':execution,'slippage':slip,'commission':commission,'trade_reason':pending['reason'],'roll_id':roll_id,'entry_trade_id':entry_id,'realized_option_PnL_gross':realized,'realized_option_PnL_net':realized_net}
