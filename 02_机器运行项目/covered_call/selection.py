"""只读取信号当日信息；到期月选择在Delta有效性过滤之前。"""
import numpy as np
import pandas as pd


def select_contract(options, signal_date, spot, strategy, cfg):
    date = pd.Timestamp(signal_date)
    if not np.isfinite(spot) or spot <= 0:
        return None, 'invalid_raw_spot'
    day = options.loc[options.date.eq(date)].copy()
    day['calendar_DTE'] = (day.expiry-date).dt.days
    eligible = day.loc[day.call_put.eq('C') & day.calendar_DTE.between(cfg['min_dte'],cfg['max_dte'])
        & day.volume.gt(0) & day.open_interest.gt(0) & day.close.gt(0)
        & day.strike.gt(0) & day.contract_multiplier.gt(0)
        & day.first_trade_date.le(date) & day.last_trade_date.ge(date)].copy()
    if cfg.get('exclude_adjusted_new_entries',True):
        eligible = eligible.loc[~eligible.adjusted_contract_flag]
    if cfg.get('next_execution_date') is not None:
        eligible=eligible.loc[eligible.expiry.gt(pd.Timestamp(cfg['next_execution_date']))]
    if eligible.empty:
        return None, 'no_eligible_expiry'
    expiries = eligible[['expiry','calendar_DTE']].drop_duplicates()
    expiries['distance'] = (expiries.calendar_DTE-cfg['target_dte']).abs()
    expiry = expiries.sort_values(['distance','expiry']).iloc[0].expiry
    eligible = eligible.loc[eligible.expiry.eq(expiry)].copy()
    if strategy == 'CC_OTM_5':
        eligible['score'] = (eligible.strike/spot-cfg['target_moneyness']).abs()
    elif strategy == 'CC_DELTA_025':
        eligible = eligible.loc[eligible.delta_wind.between(0,1)].copy()
        if eligible.empty:
            return None, 'missing_signal:wind_delta_in_target_expiry'
        eligible['score'] = (eligible.delta_wind-cfg['target_delta']).abs()
    else:
        raise ValueError('未知策略')
    selected = eligible.sort_values(['score','strike','option_code']).iloc[0].to_dict()
    selected['signal_date'] = date
    selected['signal_spot'] = spot
    return selected, 'selected'


def mark_price(row):
    for field in ['settle','close']:
        value = row.get(field,np.nan)
        if pd.notna(value) and np.isfinite(value) and value >= 0:
            return float(value), field
    raise ValueError('missing_option_mark:禁止前向填充')


def execution_valid(row, date, opening):
    if row is None:
        return False, 'missing_quote_or_terms'
    if not np.isfinite(row.get('close',np.nan)) or row['close'] <= 0:
        return False, 'invalid_close'
    if not (row['first_trade_date'] <= date <= row['last_trade_date']):
        return False, 'invalid_contract_status'
    if date > row['expiry'] or (opening and date >= row['expiry']):
        return False, 'expired_contract'
    if not np.isfinite(row.get('volume',np.nan)) or row['volume'] <= 0:
        return False, 'zero_execution_volume'
    return True, ''
