"""只读本地Parquet查询接口；没有网站、联网数据库或自动推荐逻辑。"""
from pathlib import Path
import json
import duckdb
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


class StrategyUniverse:
    def __init__(self, run_directory=None):
        if run_directory is None:
            pointer=json.loads((ROOT/'outputs/strategy_universe/latest_run.json').read_text(encoding='utf-8'))
            if pointer.get('status')!='VALIDATED':
                raise ValueError('最新批次尚未通过最终验收；审计人员可显式指定运行目录读取中间结果')
            run_directory=ROOT/'outputs/strategy_universe'/pointer['run_id']
        self.path=Path(run_directory).resolve()
        self.registry=pd.read_parquet(self.path/'strategy_registry.parquet')
        if len(self.registry)!=576 or self.registry.strategy_id.nunique()!=576:
            raise ValueError('策略注册表不完整')

    def _table(self, name, period='FULL_HISTORY', where='', values=(), order=''):
        if period not in ['FULL_HISTORY','COMMON_PERIOD']: raise ValueError('历史区间只能是FULL_HISTORY或COMMON_PERIOD')
        folder=self.path if period=='FULL_HISTORY' else self.path/'common_period'
        path=folder/(name+'.parquet')
        if not path.exists(): raise FileNotFoundError('缺少已验证的结果表: '+str(path))
        with duckdb.connect() as conn:
            sql='SELECT * FROM read_parquet(?)'+(' WHERE '+where if where else '')+(' ORDER BY '+order if order else '')
            return conn.execute(sql,[str(path),*values]).df()

    def _check(self, strategy_id, scenario_id):
        if strategy_id not in set(self.registry.strategy_id): raise KeyError('未知strategy_id: '+str(strategy_id))
        if scenario_id not in ['BASE','STRESS']: raise ValueError('scenario_id必须为BASE/STRESS')

    def get_strategy(self, params=None, **kwargs):
        p={**(params or {}),**kwargs}
        allowed={'selection_method','target_delta','target_otm','target_dte','roll_dte','coverage_ratio'}
        if set(p)-allowed: raise ValueError('未知结构参数: '+str(set(p)-allowed))
        if p.get('selection_method')=='OTM': p['selection_method']='MONEYNESS'
        r=self.registry
        for key,value in p.items():
            r=r.loc[r[key].sub(value).abs().lt(1e-10)] if isinstance(value,(int,float)) else r.loc[r[key].eq(value)]
        if len(r)!=1: raise ValueError(f'参数匹配{len(r)}个模块；请提供完整四类参数')
        return r.iloc[0].to_dict()

    def get_nav(self,strategy_id,scenario_id='BASE',period='FULL_HISTORY',start=None,end=None):
        self._check(strategy_id,scenario_id)
        where='strategy_id=? AND scenario_id=?';values=[strategy_id,scenario_id]
        if start: where+=' AND date>=?';values.append(str(start))
        if end: where+=' AND date<=?';values.append(str(end))
        return self._table('strategy_daily',period,where,values,'date')

    def get_day(self,strategy_id,date,scenario_id='BASE',period='FULL_HISTORY'):
        return self.get_nav(strategy_id,scenario_id,period,start=date,end=date)

    def compare_strategies(self,strategy_ids,scenario_id='BASE',period='COMMON_PERIOD'):
        if not 2<=len(strategy_ids)<=5 or len(set(strategy_ids))!=len(strategy_ids):
            raise ValueError('比较需要2至5个不同strategy_id')
        for strategy_id in strategy_ids: self._check(strategy_id,scenario_id)
        if period=='FULL_HISTORY':
            dates=self.registry.set_index('strategy_id').loc[strategy_ids,'effective_start_date']
            if dates.nunique()>1: raise ValueError('历史起点不同，请使用COMMON_PERIOD')
        return self._table('strategy_daily',period,'scenario_id=? AND strategy_id IN ('+','.join('?' for _ in strategy_ids)+')',
                           [scenario_id,*strategy_ids],'date,strategy_id')

    def get_latest_state(self,strategy_id,scenario_id='BASE'):
        self._check(strategy_id,scenario_id)
        return self._table('strategy_latest_state_scenarios',where='strategy_id=? AND scenario_id=?',values=[strategy_id,scenario_id])

    def _strategy_table(self,name,strategy_id,scenario_id,period,order=''):
        self._check(strategy_id,scenario_id)
        return self._table(name,period,'strategy_id=? AND scenario_id=?',[strategy_id,scenario_id],order)

    def get_metrics(self,strategy_id,scenario_id='BASE',period='FULL_HISTORY'):
        return self._strategy_table('strategy_metrics',strategy_id,scenario_id,period)

    def get_trades(self,strategy_id,scenario_id='BASE',period='FULL_HISTORY'):
        return self._strategy_table('strategy_trades',strategy_id,scenario_id,period,'execution_date,trade_id')

    def get_rolls(self,strategy_id,scenario_id='BASE',period='FULL_HISTORY'):
        return self._strategy_table('strategy_rolls',strategy_id,scenario_id,period,'execution_date,roll_id')

    def get_regime_metrics(self,strategy_id,scenario_id='BASE',period='FULL_HISTORY'):
        return self._strategy_table('strategy_regime_metrics',strategy_id,scenario_id,period,'regime_dimension,regime_value')

    def get_parameter_slice(self,scenario_id='BASE',period='COMMON_PERIOD',**fixed):
        allowed={'selection_method','target_delta','target_otm','target_dte','roll_dte','coverage_ratio'}
        if set(fixed)-allowed: raise ValueError('未知固定参数')
        if scenario_id not in ['BASE','STRESS']: raise ValueError('scenario_id必须为BASE/STRESS')
        if fixed.get('selection_method')=='OTM': fixed['selection_method']='MONEYNESS'
        where='scenario_id=?';values=[scenario_id]
        for key,value in fixed.items(): where+=f' AND {key}=?';values.append(value)
        return self._table('strategy_parameter_cube',period,where,values,'strategy_id')


def get_strategy(params): return StrategyUniverse().get_strategy(params)
def get_nav(strategy_id,**kwargs): return StrategyUniverse().get_nav(strategy_id,**kwargs)
def compare_strategies(strategy_ids,**kwargs): return StrategyUniverse().compare_strategies(strategy_ids,**kwargs)
def get_latest_state(strategy_id,**kwargs): return StrategyUniverse().get_latest_state(strategy_id,**kwargs)
def get_metrics(strategy_id,**kwargs): return StrategyUniverse().get_metrics(strategy_id,**kwargs)
def get_trades(strategy_id,**kwargs): return StrategyUniverse().get_trades(strategy_id,**kwargs)
def get_rolls(strategy_id,**kwargs): return StrategyUniverse().get_rolls(strategy_id,**kwargs)
def get_regime_metrics(strategy_id,**kwargs): return StrategyUniverse().get_regime_metrics(strategy_id,**kwargs)
def get_parameter_slice(**kwargs): return StrategyUniverse().get_parameter_slice(**kwargs)
