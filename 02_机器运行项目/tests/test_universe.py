import unittest
import copy
import numpy as np
import pandas as pd
from test_covered_call import fixture
from covered_call.margin_engine import PreparedMarket,run_margin_backtest
from covered_call.selection import select_contract
from covered_call.universe_config import registry,SCENARIOS,DEFAULTS


class UniverseTests(unittest.TestCase):
    def params(self, **kwargs):
        return dict(selection_method='MONEYNESS',target_otm=.05,target_delta=np.nan,
                    target_dte=30,roll_dte=1,coverage_ratio=1.,**kwargs)

    def run_case(self, market=None, params=None, end='2025-02-06'):
        return run_margin_backtest(PreparedMarket(market or fixture()),params or self.params(),
                                   '2025-01-02',end,SCENARIOS['BASE'])

    def test_exact_registry(self):
        r=registry();self.assertEqual(len(r),576)
        self.assertIn('CC_D25_DTE30_R5_C100',r.strategy_id.values)
        self.assertIn('CC_ATM_DTE30_R5_C100',r.strategy_id.values)
        pd.testing.assert_frame_equal(r,registry())

    def test_r1_signal_and_expiry_execution(self):
        f,s=self.run_case();self.assertTrue(s['completed'])
        r=f['rolls'].iloc[0]
        self.assertEqual(r.signal_date,pd.Timestamp('2025-02-04'))
        self.assertEqual(r.execution_date,pd.Timestamp('2025-02-05'))
        self.assertEqual(r.old_DTE,0)

    def test_atomic_net_financing(self):
        m=fixture();mask=m['options'].date.ge('2025-02-05')
        m['options'].loc[mask & m['options'].option_code.eq('C1'),['close','settle']]=.6
        m['options'].loc[mask & m['options'].option_code.eq('C2'),['close','settle']]=.55
        f,s=self.run_case(m);self.assertTrue(s['completed'])
        r=f['rolls'].iloc[0];self.assertGreater(r.buyback_cost,200000)
        self.assertLess(r.financing_after,30000)
        self.assertGreater(r.financing_after,0)
        self.assertGreaterEqual(f['ledger'].cash_balance.min(),0)
        self.assertGreater(f['daily'].financing_interest.sum(),0)
        d=f['daily'];self.assertLess((d.NAV-d.cash-d.ETF_market_value-d.option_market_value+d.financing_balance).abs().max(),1e-8)

    def test_cash_debt_ledger_rebuild(self):
        f,_=self.run_case();d=f['daily'].set_index('date');l=f['ledger']
        self.assertTrue(np.allclose(l.groupby('date').amount.sum().reindex(d.index,fill_value=0).cumsum(),d.cash))
        self.assertTrue(np.allclose(l.groupby('date').debt_change.sum().reindex(d.index,fill_value=0).cumsum(),d.financing_balance))

    def test_coverage_integer_maximum(self):
        p=self.params();p['coverage_ratio']=.5
        f,_=self.run_case(params=p);e=f['trades'].query("side=='SELL_TO_OPEN'")
        shares=f['daily'].ETF_shares.max()
        self.assertTrue((e.contracts*e.contract_multiplier/shares<=.5).all())
        self.assertTrue(((e.contracts+1)*e.contract_multiplier/shares>.5).all())

    def test_corporate_no_silent_rebalance(self):
        f,_=self.run_case(fixture(corporate=True));d=f['daily']
        self.assertTrue(d.over_target_coverage.any());self.assertTrue(d.naked_exposure.any())
        self.assertEqual(len(f['trades'].query("instrument=='ETF'")),1)

    def test_no_delta_fallback(self):
        m=fixture();m['options']['delta_wind']=np.nan;m['options']['delta_primary']=.25
        p=self.params();p.update(selection_method='DELTA',target_delta=.25)
        f,_=self.run_case(m,p)
        self.assertEqual(len(f['trades'].query("instrument=='OPTION'")),0)
        self.assertTrue(f['daily'].strategy_state.eq('MISSING_SIGNAL').all())

    def test_selection_matches_existing(self):
        m=fixture();p=self.params();date=pd.Timestamp('2025-01-02')
        actual,_=PreparedMarket(m).select(date,p,DEFAULTS)
        expected,_=select_contract(m['options'],date,2.8,'CC_OTM_5',dict(DEFAULTS,target_dte=30,target_moneyness=1.05))
        self.assertEqual(actual['option_code'],expected['option_code'])

    def test_missing_mark_fail_no_fill(self):
        m=fixture();m['options'].loc[m['options'].date.eq('2025-01-10') & m['options'].option_code.eq('C1'),['settle','close']]=np.nan
        f,s=self.run_case(m);self.assertFalse(s['completed']);self.assertIn('missing_held_mark',s['failure_reason'])
        self.assertEqual(f['daily'].date.max(),pd.Timestamp('2025-01-09'))

    def test_failed_new_leg_keeps_old(self):
        m=fixture();p=self.params();p['roll_dte']=3
        m['options'].loc[m['options'].date.eq('2025-02-03') & m['options'].option_code.eq('C2'),'volume']=0
        f,s=self.run_case(m,p);self.assertTrue(s['completed'])
        self.assertFalse(f['trades'].execution_date.eq('2025-02-03').any())
        self.assertEqual(f['daily'].set_index('date').loc['2025-02-03','short_call_code'],'C1')

    def test_future_quote_does_not_change_signal(self):
        m=fixture();before,_=PreparedMarket(m).select(pd.Timestamp('2025-01-02'),self.params(),DEFAULTS)
        m['options'].loc[m['options'].date.gt('2025-01-02'),'strike']=99
        after,_=PreparedMarket(m).select(pd.Timestamp('2025-01-02'),self.params(),DEFAULTS)
        self.assertEqual(before['option_code'],after['option_code']);self.assertEqual(before['strike'],after['strike'])

    def test_determinism(self):
        a,sa=self.run_case();b,sb=self.run_case()
        for key in a: pd.testing.assert_frame_equal(a[key],b[key])
        self.assertEqual(sa,sb)

    def test_expiry_risk_close_is_explicit(self):
        m=fixture();m['options'].loc[m['options'].date.eq('2025-02-05') & m['options'].option_code.eq('C2'),'volume']=0
        f,s=self.run_case(m);self.assertTrue(s['completed'])
        self.assertEqual(f['rolls'].iloc[0].status,'EXPIRY_RISK_CLOSE_ONLY')
        exits=f['trades'].loc[f['trades'].execution_date.eq(pd.Timestamp('2025-02-05'))]
        self.assertEqual(len(exits),1);self.assertEqual(exits.iloc[0].side,'BUY_TO_CLOSE')
        self.assertEqual(f['daily'].set_index('date').loc['2025-02-05','short_call_contracts'],0)

    def test_same_contract_roll_is_not_suppressed(self):
        p=self.params();p.update(target_dte=20,roll_dte=10)
        f,s=self.run_case(params=p);self.assertTrue(s['completed'])
        self.assertTrue(f['rolls'].same_contract.any())
        self.assertTrue(f['rolls'].loc[f['rolls'].same_contract,'net_roll_cashflow'].lt(0).all())

    def test_financing_actual_calendar_days(self):
        m=fixture();p=self.params();p['roll_dte']=10
        m['options'].loc[m['options'].date.ge('2025-01-24') & m['options'].option_code.eq('C1'),['close','settle']]=.6
        f,s=self.run_case(m,p);self.assertTrue(s['completed'])
        d=f['daily'].set_index('date')
        for i in range(1,len(d)):
            self.assertAlmostEqual(d.financing_interest.iloc[i],d.financing_balance.iloc[i-1]*.06*(d.index[i]-d.index[i-1]).days/365,places=8)

    def test_insolvency_stops_new_borrowing(self):
        m=fixture();m['options'].loc[m['options'].date.eq('2025-01-10') & m['options'].option_code.eq('C1'),['close','settle']]=20.
        f,s=self.run_case(m);self.assertFalse(s['completed'])
        self.assertEqual(f['daily'].iloc[-1].strategy_state,'STOPPED')
        self.assertEqual(f['daily'].date.max(),pd.Timestamp('2025-01-10'))

    def test_regime_labels_cannot_change_engine(self):
        m=fixture();a,_=self.run_case(m)
        m['underlying']['trend_regime']='TREND_DOWN';m['options']['iv_regime']='IV_HIGH'
        b,_=self.run_case(m)
        for key in a: pd.testing.assert_frame_equal(a[key],b[key])

    def test_full_independent_audit_and_mutation(self):
        from covered_call.universe_analytics import audit_frames
        m=fixture();p=PreparedMarket(m);f,s=self.run_case(m)
        audit_frames(f,p,self.params())
        f['daily'].loc[5,'financing_balance']+=100
        with self.assertRaises(AssertionError): audit_frames(f,p,self.params())

    def test_new_engine_dividend_not_double_counted(self):
        m=fixture();m['underlying'].loc[m['underlying'].date.ge('2025-01-15'),'close']-=.05
        m['dividends']=pd.DataFrame({'date':[pd.Timestamp('2025-01-15')],'dividend_per_share':[.05]})
        f,s=self.run_case(m);self.assertTrue(s['completed'])
        row=f['daily'].set_index('date').loc['2025-01-15']
        self.assertAlmostEqual(row.ETF_pnl+row.dividend_pnl,0.,places=8)

    def test_rolling_excess_uses_calendar_month_not_future(self):
        from covered_call.universe_analytics import add_benchmark
        dates=pd.bdate_range('2024-01-02','2024-12-31')
        daily=pd.DataFrame({'date':dates,'NAV':1e6*np.power(1.001,np.arange(len(dates)))})
        bench=pd.DataFrame({'date':dates,'NAV':1e6*np.power(1.0005,np.arange(len(dates)))})
        result=add_benchmark(daily,bench)
        i=dates.get_loc('2024-07-01');cutoff=pd.Timestamp('2024-04-01');prior=dates.searchsorted(cutoff,side='right')-1
        expected=daily.NAV.iloc[i]/daily.NAV.iloc[prior]-bench.NAV.iloc[i]/bench.NAV.iloc[prior]
        self.assertAlmostEqual(result.rolling_excess_3M.iloc[i],expected)
        self.assertTrue(result.loc[result.date.lt('2024-04-02'),'rolling_excess_3M'].isna().all())

    def test_shared_market_order_independence(self):
        prepared=PreparedMarket(fixture());a=self.params();b=dict(a,target_dte=20,roll_dte=10,coverage_ratio=.5)
        first,_=run_margin_backtest(prepared,a,'2025-01-02','2025-02-06',SCENARIOS['BASE'])
        run_margin_backtest(prepared,b,'2025-01-02','2025-02-06',SCENARIOS['STRESS'])
        repeated,_=run_margin_backtest(prepared,a,'2025-01-02','2025-02-06',SCENARIOS['BASE'])
        for key in first: pd.testing.assert_frame_equal(first[key],repeated[key])

    def test_long_holiday_must_not_select_t1_expiring_call(self):
        m=fixture();m['calendar']=pd.Series(pd.to_datetime(['2025-01-02','2025-01-03','2025-02-05','2025-02-06','2025-03-05']))
        m['underlying']=m['underlying'].loc[m['underlying'].date.isin(m['calendar'])]
        m['options']=m['options'].loc[m['options'].date.isin(m['calendar'])]
        p=PreparedMarket(m);param=self.params();param['target_dte']=30
        old,_=p.select(pd.Timestamp('2025-01-03'),param,dict(DEFAULTS,require_valid_t1=False))
        new,_=p.select(pd.Timestamp('2025-01-03'),param,DEFAULTS)
        self.assertEqual(old['option_code'],'C1');self.assertEqual(new['option_code'],'C2')


if __name__=='__main__': unittest.main()
