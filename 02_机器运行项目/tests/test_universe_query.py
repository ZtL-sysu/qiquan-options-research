from pathlib import Path
import tempfile
import unittest
import pandas as pd
from covered_call.query import StrategyUniverse
from covered_call.universe_config import registry


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        reg=registry();reg['effective_start_date']=pd.Timestamp('2015-02-09')
        reg.loc[reg.selection_method.eq('DELTA'),'effective_start_date']=pd.Timestamp('2020-12-08')
        reg.to_parquet(self.path/'strategy_registry.parquet',index=False)
        self.api=StrategyUniverse(self.path)

    def tearDown(self): self.temp.cleanup()

    def test_param_lookup_and_stable_id(self):
        p=dict(selection_method='DELTA',target_delta=.25,target_dte=30,roll_dte=5,coverage_ratio=1.)
        self.assertEqual(self.api.get_strategy(p)['strategy_id'],'CC_D25_DTE30_R5_C100')

    def test_ambiguous_lookup_rejected(self):
        with self.assertRaises(ValueError): self.api.get_strategy(dict(target_dte=30))

    def test_mixed_history_comparison_rejected(self):
        with self.assertRaises(ValueError):
            self.api.compare_strategies(['CC_D25_DTE30_R5_C100','CC_OTM05_DTE30_R5_C100'],period='FULL_HISTORY')

    def test_unknown_id_not_sql_injected(self):
        with self.assertRaises(KeyError): self.api.get_nav("' OR 1=1 --")

    def test_compare_count_limits(self):
        with self.assertRaises(ValueError): self.api.compare_strategies(['CC_D25_DTE30_R5_C100'])

    def test_missing_result_file_not_silent_empty(self):
        with self.assertRaises(FileNotFoundError): self.api.get_nav('CC_D25_DTE30_R5_C100')

    def test_common_nav_dates(self):
        folder=self.path/'common_period';folder.mkdir()
        sid='CC_D25_DTE30_R5_C100'
        pd.DataFrame({'strategy_id':[sid,sid],'scenario_id':['BASE','BASE'],
                      'date':pd.to_datetime(['2025-01-02','2025-01-03']),'NAV':[1e6,1.01e6]}).to_parquet(folder/'strategy_daily.parquet',index=False)
        result=self.api.get_nav(sid,period='COMMON_PERIOD',start='2025-01-03')
        self.assertEqual(len(result),1);self.assertEqual(result.NAV.iloc[0],1.01e6)


if __name__=='__main__': unittest.main()
