import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

import numpy as np
import pandas as pd
import yaml

from covered_call.data import ROOT, assert_unique, build_terms, build_dividends
from covered_call.selection import select_contract, mark_price
from covered_call.engine import run_backtest
from covered_call.metrics import independent_reconciliation, source_reconciliation

CFG=yaml.safe_load((ROOT/'config/covered_call.yaml').read_text(encoding='utf-8'))


def fixture(corporate=False):
    cal=pd.bdate_range('2025-01-02','2025-04-01')
    dates=cal[cal<=pd.Timestamp('2025-02-06')]
    rows=[]
    for date in dates:
        for code,expiry in [('C1','2025-02-05'),('C2','2025-03-05')]:
            if date>pd.Timestamp(expiry):
                continue
            changed=corporate and code=='C1' and date>=pd.Timestamp('2025-01-15')
            close=.02 if date<=pd.Timestamp('2025-01-03') else .005
            rows.append({'date':date,'option_code':code,'call_put':'C','expiry':pd.Timestamp(expiry),
                'first_trade_date':dates.min(),'last_trade_date':pd.Timestamp(expiry),'volume':100.,'open_interest':1000.,
                'close':close,'settle':close+.001,'strike':2.88 if changed else 2.94,'contract_multiplier':10300. if changed else 10000.,
                'exchange_code':code+('A' if changed else 'M'),'adjusted_contract_flag':changed,'delta_wind':.25,'iv_wind':.2})
    u=pd.DataFrame({'date':dates,'close':2.8,'adjusted_close':999.0})
    return {'calendar':pd.Series(cal),'options':pd.DataFrame(rows),'underlying':u,'dividends':pd.DataFrame({'date':pd.to_datetime([]),'dividend_per_share':pd.Series(dtype=float)})}


class Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d=pd.read_csv(ROOT/'data_audit/sample_option_chain.csv')
        d=d.rename(columns={'trade_date':'date','implied_vol':'iv_wind'})
        for c in ['date','expiry','first_trade_date','last_trade_date']:
            d[c]=pd.to_datetime(d[c].astype(str))
        cls.day=d

    def test_required_otm_20250715(self):
        row,reason=select_contract(self.day,'2025-07-15',2.855,'CC_OTM_5',CFG)
        self.assertEqual(row['expiry'],pd.Timestamp('2025-08-27'),'目标期限的到期月改变')
        self.assertEqual(row['calendar_DTE'],43)
        self.assertEqual(row['strike'],3.0,'OTM目标应选3.00')

    def test_required_delta_20250715(self):
        row,_=select_contract(self.day,'2025-07-15',2.855,'CC_DELTA_025',CFG)
        self.assertEqual(row['expiry'],pd.Timestamp('2025-08-27'))
        self.assertEqual(row['strike'],2.95,'Wind Delta应选2.95，不是3.00')
        self.assertAlmostEqual(row['delta_wind'],.2752)
        v=self.day.loc[self.day.expiry.eq(pd.Timestamp('2025-08-27'))&self.day.strike.eq(3.0),'delta_wind'].iloc[0]
        self.assertAlmostEqual(v,.1918)

    def test_no_delta_source_fallback(self):
        day=self.day.copy();day.loc[day.expiry.eq(pd.Timestamp('2025-08-27')),'delta_wind']=np.nan
        day['delta']=.25
        row,reason=select_contract(day,'2025-07-15',2.855,'CC_DELTA_025',CFG)
        self.assertIsNone(row);self.assertIn('missing_signal',reason)

    def test_future_rows_do_not_affect_signal(self):
        future=self.day.copy();future['date']=pd.Timestamp('2025-07-16');future['delta_wind']=.25;future['strike']=2.855*1.05
        today,_=select_contract(self.day,'2025-07-15',2.855,'CC_OTM_5',CFG)
        mixed,_=select_contract(pd.concat([self.day,future]),'2025-07-15',2.855,'CC_OTM_5',CFG)
        self.assertEqual(today['option_code'],mixed['option_code'])

    def test_otm_independent_of_greeks(self):
        day=self.day.copy();day['delta_wind']=np.nan
        row,_=select_contract(day,'2025-07-15',2.855,'CC_OTM_5',CFG)
        self.assertEqual(row['strike'],3.0)

    def test_raw_spot_only(self):
        day=self.day.copy();day['adjusted_close']=12345.
        row,_=select_contract(day,'2025-07-15',2.855,'CC_OTM_5',CFG)
        self.assertEqual(row['strike'],3.0)


class LedgerTest(unittest.TestCase):
    def run_fixture(self,m=None,cfg=None):
        return run_backtest(m or fixture(),'CC_OTM_5','2025-01-02','2025-02-06',cfg or CFG,.005)

    def test_signal_next_day_and_roll_trace(self):
        frames,status=self.run_fixture()
        self.assertTrue(status['completed'],status)
        trades=frames['trades']
        self.assertTrue((trades.execution_date>trades.signal_date).all())
        first=trades.loc[trades.instrument.eq('OPTION')].iloc[0]
        self.assertEqual(first.signal_date,pd.Timestamp('2025-01-02'))
        self.assertEqual(first.execution_date,pd.Timestamp('2025-01-03'))
        roll=frames['roll_events'].iloc[0]
        self.assertEqual((roll.old_contract,roll.new_contract),('C1','C2'))
        self.assertEqual(roll.execution_date,pd.Timestamp('2025-02-04'))
        self.assertEqual(roll.status,'complete')

    def test_independent_daily_reconciliation(self):
        frames,_=self.run_fixture()
        errors=independent_reconciliation(frames,CFG).drop(columns='date')
        self.assertLess(errors.abs().to_numpy().max(),1e-6)

    def test_source_price_and_signal_reconciliation(self):
        m=fixture();frames,_=self.run_fixture(m)
        self.assertTrue(source_reconciliation(frames,m).passed.all())
        idx=frames['trades'].index[frames['trades'].instrument.eq('OPTION')][0]
        frames['trades'].loc[idx,'signal_strike']+=.1
        with self.assertRaises(AssertionError):
            source_reconciliation(frames,m)

    def test_roll_closes_old_when_new_delta_missing(self):
        m=fixture();day=pd.Timestamp('2025-02-03')
        m['options'].loc[m['options'].date.eq(day),'delta_wind']=np.nan
        frames,status=run_backtest(m,'CC_DELTA_025','2025-01-02','2025-02-06',CFG,.005)
        self.assertTrue(status['completed'])
        event=frames['roll_events'].iloc[0]
        self.assertEqual(event.status,'closed_only')
        pos=frames['option_positions'].set_index('date').loc[pd.Timestamp('2025-02-04')]
        self.assertEqual(pos.option_quantity,0)

    def test_integer_contracts_and_closed_position_zero(self):
        frames,_=self.run_fixture()
        trades=frames['trades'].query("instrument=='OPTION'")
        self.assertTrue((trades.contracts%1==0).all())
        q=0
        for _,row in trades.iterrows():
            q+=-row.contracts if row.side=='SELL_TO_OPEN' else row.contracts
            if row.side=='BUY_TO_CLOSE':
                self.assertEqual(q,0)

    def test_missing_option_mark_stops_not_ffill(self):
        m=fixture();bad=m['options'].date.eq(pd.Timestamp('2025-01-10'))&m['options'].option_code.eq('C1')
        m['options'].loc[bad,['close','settle']]=np.nan
        frames,status=self.run_fixture(m)
        self.assertFalse(status['completed']);self.assertIn('前向填充',status['reason'])
        self.assertLess(frames['daily_nav'].date.max(),pd.Timestamp('2025-01-10'))
        independent_reconciliation(frames,CFG)

    def test_settlement_then_close_no_previous_day(self):
        self.assertEqual(mark_price({'settle':.01,'close':.02}),(.01,'settle'))
        self.assertEqual(mark_price({'settle':np.nan,'close':.02}),(.02,'close'))
        with self.assertRaises(ValueError):
            mark_price({'settle':np.nan,'close':np.nan})

    def test_bad_execution_is_logged(self):
        m=fixture();m['options'].loc[m['options'].date.eq(pd.Timestamp('2025-01-03')),'close']=0.
        frames,_=self.run_fixture(m)
        self.assertIn('invalid_close',frames['missed_trade_log'].reason.tolist())

    def test_dividend_uses_prior_holdings_not_adjusted_returns(self):
        m=fixture();day=pd.Timestamp('2025-01-10')
        m['dividends']=pd.DataFrame({'date':[day],'dividend_per_share':[.01]})
        m['underlying'].loc[m['underlying'].date>=day,'close']-=.01
        frames,_=self.run_fixture(m)
        r=frames['daily_nav'].set_index('date').loc[day]
        self.assertAlmostEqual(r.ETF_PnL+r.dividend_PnL,0.,places=6)
        self.assertEqual(len(frames['dividend_ledger']),1)
        independent_reconciliation(frames,CFG)

    def test_adjustment_does_not_trade_etf_and_flags_coverage(self):
        frames,_=self.run_fixture(fixture(True))
        exposure=frames['daily_exposure'].set_index('date')
        self.assertTrue(exposure.loc[pd.Timestamp('2025-01-15'),'undercovered'])
        self.assertEqual(len(frames['trades'].query("instrument=='ETF'")),1)
        positions=frames['option_positions'].set_index('date')
        self.assertEqual(positions.loc[pd.Timestamp('2025-01-14'),'contract_multiplier'],10000)
        self.assertEqual(positions.loc[pd.Timestamp('2025-01-15'),'contract_multiplier'],10300)

    def test_no_roll_from_truncated_end_calendar(self):
        m=fixture()
        frames,status=run_backtest(m,'CC_OTM_5','2025-01-02','2025-01-10',CFG,.005)
        self.assertTrue(status['completed']);self.assertTrue(frames['roll_events'].empty)

    def test_cost_addback_is_same_position_gross(self):
        frames,_=self.run_fixture()
        d=frames['daily_nav']
        np.testing.assert_allclose(d.gross_NAV_same_positions,d.NAV+d.transaction_cost.cumsum())

    def test_no_silent_financing(self):
        m=fixture()
        m['options'].loc[m['options'].date.ge(pd.Timestamp('2025-02-04'))&m['options'].option_code.eq('C1'),['close','settle']]=2.
        frames,status=self.run_fixture(m)
        self.assertFalse(status['completed'])
        self.assertIn('insufficient_cash_no_implicit_financing',frames['missed_trade_log'].reason.tolist())
        self.assertTrue(frames['daily_nav'].cash.ge(0).all())


class DataTest(unittest.TestCase):
    def test_unique_option_date(self):
        with tempfile.TemporaryDirectory() as tmp, patch('covered_call.data.MART',Path(tmp)):
            with self.assertRaises(ValueError):
                assert_unique(pd.DataFrame({'option_code':['X','X'],'date':[1,1]}),['option_code','date'],'unit_test_duplicate')

    def test_no_future_strike_or_multiplier(self):
        desc=pd.read_csv(ROOT/'data_audit/sample_active_descriptions_raw.csv',dtype=str)
        changes=pd.read_csv(ROOT/'data_audit/sample_contract_adjustments.csv',dtype=str)
        term=build_terms(desc,changes,pd.to_datetime(['2025-07-15']))
        row=term.set_index('option_code').loc['10009217.SH']
        self.assertEqual((row.strike,row.contract_multiplier),(2.5,10000.))


if __name__=='__main__':
    unittest.main()
