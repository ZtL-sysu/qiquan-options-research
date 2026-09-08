"""单表取数、增量缓存、历史条款恢复和标准数据质量核对。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MART = ROOT / 'data_mart'
sys.path.insert(0, str(ROOT / 'data_audit'))
from audit_db import AuditDB  # noqa: E402
from validate_sample import historical_terms, decode_exchange_code  # noqa: E402


def json_write(value, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding='utf-8')


def parquet_write(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp.parquet')
    frame.to_parquet(temp, index=False)
    temp.replace(path)


def numeric_frame(rows, columns):
    frame = pd.DataFrame(rows, columns=columns)
    # Decimal转float；日期和标识符始终保留字符串。
    for column in frame.columns:
        if column.startswith(('S_DQ_', 'W_ANAL_', 'F_NAV_')) or column in ['THEORE_PRICE', 'IS_EXDIVIDENDDATE']:
            frame[column] = pd.to_numeric(frame[column], errors='raise')
    return frame


def assert_unique(frame, keys, name):
    duplicated = frame.duplicated(keys, keep=False)
    if duplicated.any():
        out = MART / 'quality' / (name + '_duplicates.csv')
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.loc[duplicated].to_csv(out, index=False, encoding='utf-8-sig')
        raise ValueError(f'{name}业务主键重复，见 {out.name}')


def write_quality_profiles(terms, eod, wind, primary):
    quality=MART/'quality';quality.mkdir(exist_ok=True)
    g=terms[['date','option_code','call_put','adjusted_contract_flag']].merge(eod,on=['date','option_code'],validate='one_to_one').merge(wind.drop(columns='source'),on=['date','option_code'],how='left',validate='one_to_one').merge(primary[['date','option_code','delta_primary']],on=['date','option_code'],how='left',validate='one_to_one')
    g['delta_abs_difference']=(g.delta_wind-g.delta_primary).abs()
    g['wind_delta_valid']=g.delta_wind.notna()
    g['close_missing']=g.close.isna()
    g['zero_volume']=g.volume.le(0)
    profile=g.groupby('date').agg(contract_count=('option_code','size'),close_missing=('close_missing','sum'),zero_volume=('zero_volume','sum'),wind_delta_nonnull=('delta_wind','count'),wind_iv_nonnull=('iv_wind','count'),primary_delta_nonnull=('delta_primary','count'),max_delta_abs_difference=('delta_abs_difference','max'))
    profile.to_csv(quality/'daily_quality.csv',encoding='utf-8-sig')
    aggregations={c:('max' if c=='max_delta_abs_difference' else 'sum') for c in profile.columns}
    profile.groupby(profile.index.year).agg(aggregations).to_csv(quality/'annual_coverage.csv',encoding='utf-8-sig')


def build_terms(desc, changes, dates):
    """复用M1验证函数构建生效区间，再展开为每个上交所交易日。"""
    dates = pd.DatetimeIndex(dates).sort_values()
    rows = []
    for _, row in desc.iterrows():
        events = changes.loc[changes.S_INFO_WINDCODE.eq(row.S_INFO_WINDCODE)].sort_values('S_CHANGE_DATE')
        first, last = pd.Timestamp(row.S_INFO_FTDATE), pd.Timestamp(row.S_INFO_LASTTRADINGDATE)
        expiry = pd.Timestamp(row.S_INFO_MATURITYDATE)
        live = dates[(dates >= first) & (dates <= min(last, expiry))]
        if live.empty:
            continue
        cuts = [live[0], *[pd.Timestamp(d) for d in events.S_CHANGE_DATE if live[0] < pd.Timestamp(d) <= live[-1]], live[-1] + pd.Timedelta(days=1)]
        for begin, end in zip(cuts[:-1], cuts[1:]):
            terms = historical_terms(row, events, begin.strftime('%Y%m%d'))
            parsed = decode_exchange_code(terms['exchange_code'])
            if parsed['underlying'] != '510050.SH':
                raise ValueError('标的映射不一致')
            period = live[(live >= begin) & (live < end)]
            frame = pd.DataFrame({'date':period, 'option_code':row.S_INFO_WINDCODE,
                'underlying_code':'510050.SH', 'call_put':{'708001000':'C','708002000':'P'}[str(row.S_INFO_CALLPUT)],
                'expiry':expiry,'first_trade_date':first,'last_trade_date':last,
                'strike':terms['strike'],'contract_multiplier':terms['contract_multiplier'],
                'exchange_code':terms['exchange_code'],'adjusted_contract_flag':parsed['adjusted'],
                'terms_source':terms['terms_source']})
            rows.append(frame)
    result = pd.concat(rows, ignore_index=True).sort_values(['date','option_code'])
    assert_unique(result,['option_code','date'],'contract_terms')
    if not result[['strike','contract_multiplier']].gt(0).all().all():
        raise ValueError('执行价或合约单位无效')
    return result


def build_dividends(nav, underlying):
    nav = nav.sort_values('PRICE_DATE').copy()
    assert_unique(nav,['PRICE_DATE'],'fund_nav')
    nav['dividend_per_share'] = nav.F_NAV_DISTRIBUTION.diff()
    events = nav.loc[nav.dividend_per_share.abs().gt(1e-9)].copy()
    if events.dividend_per_share.lt(0).any() or not events.IS_EXDIVIDENDDATE.eq(1).all():
        raise ValueError('累计分配变化与除权标志不一致，不能直接构造分红')
    events['date'] = pd.to_datetime(events.PRICE_DATE)
    u = underlying.sort_values('date').copy()
    u['price_dividend_check'] = u.close.shift(1) - u.preclose
    events = events.merge(u[['date','price_dividend_check']],on='date',how='left',validate='one_to_one')
    supported = events.price_dividend_check.notna()
    if not np.allclose(events.loc[supported,'dividend_per_share'],events.loc[supported,'price_dividend_check'],atol=1e-6,rtol=0):
        raise ValueError('分红金额与ETF除权价格差不一致')
    events['economic_accrual_date'] = events.date
    events['cash_payment_date'] = pd.NaT
    events['source'] = 'chinamutualfundnav.F_NAV_DISTRIBUTION.diff; IS_EXDIVIDENDDATE=1'
    events['date_convention'] = '除息日经济应计，非实际现金支付日'
    return events[['date','dividend_per_share','economic_accrual_date','cash_payment_date','price_dividend_check','source','date_convention']]


def underlying_return_check(underlying, dividends, dates):
    u=underlying.sort_values('date').merge(dividends[['date','dividend_per_share']],on='date',how='left',validate='one_to_one')
    u['dividend_per_share']=u.dividend_per_share.fillna(0)
    u['raw_plus_dividend_return']=(u.close+u.dividend_per_share)/u.close.shift(1)-1
    u['adjusted_return_check']=u.adjusted_close/u.adjusted_close.shift(1)-1
    u['return_difference']=u.raw_plus_dividend_return-u.adjusted_return_check
    u=u.loc[u.date.isin(dates)]
    (MART/'quality').mkdir(exist_ok=True)
    u.to_csv(MART/'quality'/'etf_total_return_consistency.csv',index=False,encoding='utf-8-sig')
    return float(u.return_difference.abs().max()*10000)


def sync(refresh=False):
    MART.mkdir(exist_ok=True)
    db = AuditDB()
    query_log = MART / 'quality' / 'sync_queries.json'
    try:
        def fetch(sql, params=()):
            return numeric_frame(db.query(sql,params), db.last_columns)
        # 原工具健康检查，失败立即退出，不继续下载。
        tool = ROOT / '00_完整数据库工具包/01_机器运行文件/国金数据库取数.py'
        spec = importlib.util.spec_from_file_location('health_tool',tool)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.command_health(None)
        prop = fetch('SELECT * FROM chinaoptioncontpro WHERE S_INFO_WINDCODE=%s',('510050.SH',))
        identity = fetch('SELECT F_INFO_WINDCODE,SEC_ID FROM chinamutualfunddescription WHERE SEC_ID=%s',(prop.iloc[0].S_INFO_UDLSECID,))
        if len(identity)!=1 or identity.iloc[0].F_INFO_WINDCODE!='510050.SH':
            raise ValueError('直接标的映射失败')
        desc = fetch('SELECT * FROM chinaoptiondescription WHERE S_INFO_SCCODE=%s', (prop.iloc[0].S_INFO_CODE,))
        # M1函数使用字符串枚举和日期。
        for col in desc:
            if col not in ['S_INFO_STRIKEPRICE','S_INFO_COUNIT','S_INFO_LPRICE']:
                desc[col] = desc[col].astype('string')
        for col in ['S_INFO_STRIKEPRICE','S_INFO_COUNIT','S_INFO_LPRICE']:
            desc[col] = pd.to_numeric(desc[col])
        assert_unique(desc,['S_INFO_WINDCODE'],'description')
        old_desc_path = MART / 'raw' / 'description.parquet'
        old_codes = set(pd.read_parquet(old_desc_path).S_INFO_WINDCODE) if old_desc_path.exists() else set()
        new_desc = desc.loc[~desc.S_INFO_WINDCODE.isin(old_codes)]
        parquet_write(desc,old_desc_path)
        changes_parts = []
        for i in range(0,len(desc),500):
            codes = desc.S_INFO_WINDCODE.iloc[i:i+500].tolist()
            changes_parts.append(fetch('SELECT * FROM coptiondescriptionchange WHERE S_INFO_WINDCODE IN ('+','.join(['%s']*len(codes))+')',codes))
        changes = pd.concat(changes_parts,ignore_index=True)
        for col in changes:
            if col not in ['S_EXERCISE_PRICE_OLD','S_EXERCISE_PRICE_NEW','S_UNIT_OLD','S_UNIT_NEW']:
                changes[col] = changes[col].astype('string')
            else:
                changes[col] = pd.to_numeric(changes[col])
        parquet_write(changes,MART/'raw'/'contract_changes.parquet')
        cutoff = (pd.Timestamp.now(tz='Asia/Shanghai').normalize()-pd.Timedelta(days=1)).strftime('%Y%m%d')
        cal = fetch('SELECT TRADE_DAYS FROM chinaoptioncalendar WHERE S_INFO_EXCHMARKET=%s AND TRADE_DAYS>=%s ORDER BY TRADE_DAYS',('SSE','20150209'))
        cal['date'] = pd.to_datetime(cal.TRADE_DAYS)
        assert_unique(cal,['date'],'calendar')
        u = fetch('SELECT S_INFO_WINDCODE,TRADE_DT,S_DQ_PRECLOSE,S_DQ_OPEN,S_DQ_HIGH,S_DQ_LOW,S_DQ_CLOSE,S_DQ_VOLUME,S_DQ_AMOUNT,S_DQ_ADJCLOSE,S_DQ_ADJFACTOR FROM chinaclosedfundeodprice WHERE S_INFO_WINDCODE=%s ORDER BY TRADE_DT',('510050.SH',))
        u = u.rename(columns={'TRADE_DT':'date','S_INFO_WINDCODE':'underlying_code',**{f'S_DQ_{a}':b for a,b in [('PRECLOSE','preclose'),('OPEN','open'),('HIGH','high'),('LOW','low'),('CLOSE','close'),('VOLUME','volume'),('AMOUNT','amount'),('ADJCLOSE','adjusted_close'),('ADJFACTOR','adjustment_factor')]}})
        u.date = pd.to_datetime(u.date)
        assert_unique(u,['date'],'underlying')
        latest_option = fetch('SELECT MAX(TRADE_DT) AS latest FROM chinaoptioneodprices WHERE TRADE_DT<=%s',(cutoff,)).iloc[0]['latest']
        end = min(u.loc[u.close.gt(0),'date'].max(),pd.Timestamp(latest_option),cal.date.max())
        dates = cal.loc[cal.date.le(end),'date']
        fields = {
            'chinaoptioneodprices':'S_INFO_WINDCODE,TRADE_DT,S_DQ_OPEN,S_DQ_HIGH,S_DQ_LOW,S_DQ_CLOSE,S_DQ_SETTLE,S_DQ_VOLUME,S_DQ_OI,S_DQ_AMOUNT',
            'windchinaoptionvaluation':'S_INFO_WINDCODE,TRADE_DT,W_ANAL_DELTA,W_ANAL_GAMMA,W_ANAL_THETA,W_ANAL_VEGA,W_ANAL_RHO,W_ANAL_UNDERLYINGIMPLIEDVOL',
            'chinaoptionvaluation':'S_INFO_WINDCODE,TRADE_DT,W_ANAL_DELTA,W_ANAL_GAMMA,W_ANAL_THETA,W_ANAL_VEGA,W_ANAL_RHO,W_ANAL_UNDERLYINGIMPLIEDVOL'}
        manifest_path = MART/'manifest.json'
        prior = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
        overlap = pd.Timestamp(prior.get('end_date','2015-02-09'))-pd.Timedelta(days=35)
        all_frames = {}
        for table, cols in fields.items():
            parts = []
            for year in range(2015,end.year+1):
                path = MART/'raw'/table/f'{year}.parquet'
                start_y,end_y = max(pd.Timestamp(f'{year}-01-01'),pd.Timestamp('2015-02-09')),min(pd.Timestamp(f'{year}-12-31'),end)
                new_in_year = ((pd.to_datetime(new_desc.S_INFO_FTDATE)<=end_y)&(pd.to_datetime(new_desc.S_INFO_LASTTRADINGDATE)>=start_y)).any()
                if path.exists() and not refresh and end_y<overlap and not new_in_year:
                    part = pd.read_parquet(path)
                else:
                    begin = start_y if refresh or not path.exists() or new_in_year else max(start_y,overlap)
                    live = desc.loc[(pd.to_datetime(desc.S_INFO_FTDATE)<=end_y)&(pd.to_datetime(desc.S_INFO_LASTTRADINGDATE)>=begin),'S_INFO_WINDCODE'].tolist()
                    batches=[]
                    for i in range(0,len(live),250):
                        codes=live[i:i+250]
                        batches.append(fetch(f'SELECT {cols} FROM {table} WHERE S_INFO_WINDCODE IN ('+','.join(['%s']*len(codes))+') AND TRADE_DT BETWEEN %s AND %s',(*codes,begin.strftime('%Y%m%d'),end_y.strftime('%Y%m%d'))))
                    part=pd.concat(batches,ignore_index=True)
                    if path.exists() and begin>start_y:
                        previous=pd.read_parquet(path)
                        part=pd.concat([previous.loc[previous.TRADE_DT<begin.strftime('%Y%m%d')],part],ignore_index=True)
                    assert_unique(part,['S_INFO_WINDCODE','TRADE_DT'],table+str(year))
                    parquet_write(part,path)
                    print(table,year,len(part),'rows',flush=True)
                parts.append(part)
            all_frames[table]=pd.concat(parts,ignore_index=True)
        terms=build_terms(desc,changes,dates)
        eod=all_frames['chinaoptioneodprices'].rename(columns={'S_INFO_WINDCODE':'option_code','TRADE_DT':'date',**{f'S_DQ_{a}':b for a,b in [('OPEN','open'),('HIGH','high'),('LOW','low'),('CLOSE','close'),('SETTLE','settle'),('VOLUME','volume'),('OI','open_interest'),('AMOUNT','amount')]}})
        eod.date=pd.to_datetime(eod.date)
        for table,suffix,path in [('windchinaoptionvaluation','wind','510050_wind_greeks.parquet'),('chinaoptionvaluation','primary','510050_primary_greeks.parquet')]:
            g=all_frames[table].rename(columns={'S_INFO_WINDCODE':'option_code','TRADE_DT':'date',**{f'W_ANAL_{a}':f'{b}_{suffix}' for a,b in [('DELTA','delta'),('GAMMA','gamma'),('THETA','theta'),('VEGA','vega'),('RHO','rho'),('UNDERLYINGIMPLIEDVOL','iv')]}})
            g.date=pd.to_datetime(g.date);g['source']=table
            assert_unique(g,['option_code','date'],suffix)
            parquet_write(g,MART/'options'/path)
        nav=fetch('SELECT PRICE_DATE,F_NAV_DISTRIBUTION,IS_EXDIVIDENDDATE FROM chinamutualfundnav WHERE F_INFO_WINDCODE=%s AND PRICE_DATE<=%s ORDER BY PRICE_DATE',('510050.SH',end.strftime('%Y%m%d')))
        div=build_dividends(nav,u)
        return_check_bps=underlying_return_check(u,div,dates)
        parquet_write(nav,MART/'raw'/'fund_nav_distribution.parquet')
        parquet_write(div.loc[div.date>=dates.min()],MART/'corporate_actions'/'510050_dividends.parquet')
        parquet_write(u.loc[u.date.isin(dates)],MART/'underlying'/'510050.parquet')
        parquet_write(pd.DataFrame({'date':cal.date,'exchange':'SSE'}),MART/'calendar'/'sse_calendar.parquet')
        parquet_write(eod,MART/'options'/'510050_option_eod.parquet')
        parquet_write(terms,MART/'options'/'510050_contract_terms_asof.parquet')
        grid=terms[['option_code','date','call_put','adjusted_contract_flag']].merge(eod[['option_code','date','close','settle']],on=['option_code','date'],how='outer',indicator=True,validate='one_to_one')
        gaps=grid.loc[grid._merge.ne('both') | (grid.close.isna()&grid.settle.isna())]
        (MART/'quality').mkdir(exist_ok=True)
        gaps.to_csv(MART/'quality'/'option_date_gaps.csv',index=False,encoding='utf-8-sig')
        latest=grid.loc[grid.date.eq(end)&grid.adjusted_contract_flag.eq(False)]
        if latest._merge.ne('both').any() or latest[['close','settle']].isna().all(axis=1).any():
            raise ValueError('最新交易日标准合约行情不完整，见option_date_gaps.csv')
        missing_etf=set(dates)-set(u.loc[u.close.gt(0),'date'])
        if missing_etf:
            raise ValueError('交易日历内ETF缺少有效原始收盘价')
        wind=pd.read_parquet(MART/'options'/'510050_wind_greeks.parquet')
        primary=pd.read_parquet(MART/'options'/'510050_primary_greeks.parquet')
        write_quality_profiles(terms,eod,wind,primary)
        wind_start=wind.loc[wind.delta_wind.between(0,1),'date'].min()
        summary={'underlying':'510050.SH','start_date':str(dates.min().date()),'end_date':str(end.date()),'calendar_days':len(dates),'description_rows':len(desc),'option_eod_rows':len(eod),'terms_rows':len(terms),'wind_rows':len(wind),'wind_delta_first_date':str(wind_start.date()),'gap_rows':len(gaps),'created_at':datetime.now().astimezone().isoformat(),'incremental_lookback_calendar_days':35,'full_refresh':refresh,'pit_limit':'业务条款按生效日恢复；源库无完整历史发布版本，无法证明当年数据发布时刻。','revision_policy':'每次刷新全部条款/分红/日历/ETF；期权行情与估值回查35自然日，新代码回补历史；更早供应商修订需--refresh。'}
        standard_files=[p for folder in ['underlying','options','corporate_actions','calendar'] for p in (MART/folder).glob('*.parquet')]
        summary['total_return_consistency_max_abs_bps']=return_check_bps
        summary['file_sha256']={str(p.relative_to(MART)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in standard_files}
        json_write(summary,manifest_path)
        print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    finally:
        db.conn.close()
        json_write(db.log,query_log)


def load_market():
    manifest=json.loads((MART/'manifest.json').read_text(encoding='utf-8'))
    for relative,expected in manifest.get('file_sha256',{}).items():
        if hashlib.sha256((MART/relative).read_bytes()).hexdigest()!=expected:
            raise ValueError('标准数据文件校验失败，可能更新未完成；请重新同步')
    terms=pd.read_parquet(MART/'options'/'510050_contract_terms_asof.parquet')
    eod=pd.read_parquet(MART/'options'/'510050_option_eod.parquet')
    wind=pd.read_parquet(MART/'options'/'510050_wind_greeks.parquet').drop(columns='source')
    market=terms.merge(eod,on=['option_code','date'],how='left',validate='one_to_one').merge(wind,on=['option_code','date'],how='left',validate='one_to_one')
    return {'options':market,'underlying':pd.read_parquet(MART/'underlying'/'510050.parquet'),
        'dividends':pd.read_parquet(MART/'corporate_actions'/'510050_dividends.parquet'),
        'calendar':pd.read_parquet(MART/'calendar'/'sse_calendar.parquet').date}
