"""历史条款恢复的边界测试；合成数据只用于单元测试，不混入真实样本。"""
import unittest

import pandas as pd

from validate_sample import historical_terms, decode_exchange_code


class TermsTest(unittest.TestCase):
    def setUp(self):
        self.row = pd.Series({"S_INFO_STRIKEPRICE":2.435, "S_INFO_COUNIT":10265,
                              "S_INFO_EXCODE":"510050C2512A02500"})
        self.events = pd.DataFrame([{"S_CHANGE_DATE":"20251217", "S_EXERCISE_PRICE_OLD":2.5,
            "S_EXERCISE_PRICE_NEW":2.435, "S_UNIT_OLD":10000, "S_UNIT_NEW":10265,
            "S_INFO_CODE_OLD":"510050C2512M02500", "S_INFO_CODE_NEW":"510050C2512A02500"}])

    def test_future_event_does_not_change_past_terms(self):
        result = historical_terms(self.row,self.events,"20250715")
        self.assertEqual((result['strike'],result['contract_multiplier']),(2.5,10000))
        self.assertFalse(decode_exchange_code(result['exchange_code'])['adjusted'])

    def test_effective_date_inclusive(self):
        result = historical_terms(self.row,self.events,"20251217")
        self.assertEqual((result['strike'],result['contract_multiplier']),(2.435,10265))
        self.assertTrue(decode_exchange_code(result['exchange_code'])['adjusted'])

    def test_static_without_event(self):
        result = historical_terms(self.row,self.events.iloc[0:0],"20251218")
        self.assertEqual(result['terms_source'],'chinaoptiondescription')

    def test_duplicate_events_rejected(self):
        with self.assertRaises(ValueError):
            historical_terms(self.row,pd.concat([self.events,self.events]),"20250715")

    def test_inconsistent_latest_snapshot_rejected(self):
        row = self.row.copy()
        row['S_INFO_COUNIT'] = 10000
        with self.assertRaises(ValueError):
            historical_terms(row,self.events,"20250715")

    def test_multiple_events_choose_next_old_terms(self):
        event2 = {"S_CHANGE_DATE":"20251220", "S_EXERCISE_PRICE_OLD":2.435,
            "S_EXERCISE_PRICE_NEW":2.4,"S_UNIT_OLD":10265,"S_UNIT_NEW":10400,
            "S_INFO_CODE_OLD":"510050C2512A02500","S_INFO_CODE_NEW":"510050C2512B02500"}
        events = pd.concat([self.events,pd.DataFrame([event2])],ignore_index=True)
        row = pd.Series({"S_INFO_STRIKEPRICE":2.4,"S_INFO_COUNIT":10400,"S_INFO_EXCODE":"510050C2512B02500"})
        result = historical_terms(row,events,"20251218")
        self.assertEqual((result['strike'],result['contract_multiplier']),(2.435,10265))

    def test_adjusted_encoded_strike_is_not_effective_strike(self):
        parsed = decode_exchange_code("510050C2512A02500")
        self.assertEqual(parsed['encoded_strike'],2.5)
        self.assertNotEqual(parsed['encoded_strike'],self.row.S_INFO_STRIKEPRICE)

    def test_invalid_code_rejected(self):
        with self.assertRaises(ValueError):
            decode_exchange_code("10009217.SH")


if __name__ == '__main__':
    unittest.main()
