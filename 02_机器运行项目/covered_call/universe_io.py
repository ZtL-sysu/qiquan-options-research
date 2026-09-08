"""统一Parquet长表写入；每次运行独立目录，避免几百份CSV。"""
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATE_COLUMNS={'date','signal_date','execution_date','expiry','entry_date','start_date','end_date',
              'first_trade_date','latest_trade_date','data_start_date','effective_start_date','latest_date','halt_date',
              'last_valid_date','requested_start','requested_end'}
STRING_COLUMNS={'strategy_id','scenario_id','period_id','run_id','parameter_version','data_version','source_hash','engine_version',
                'short_call_code','mark_source','strategy_state','event_flags','signal','next_action','selection_reason',
                'trade_id','option_code','instrument','side','trade_reason','roll_id','old_option','new_option','status',
                'event','reference','reason','failure_reason','regime_dimension','regime_value','selection_method',
                'strategy_family','current_option'}
EVENT_COLUMNS=['date','event','option_code','reason','old_multiplier','new_multiplier','old_strike','new_strike','coverage_ratio']


def normalize(frame):
    frame=frame.copy()
    for col in frame:
        if col in DATE_COLUMNS: frame[col]=pd.to_datetime(frame[col])
        elif col in STRING_COLUMNS: frame[col]=frame[col].astype('string')
        elif pd.api.types.is_bool_dtype(frame[col]): frame[col]=frame[col].astype(bool)
        elif pd.api.types.is_numeric_dtype(frame[col]): frame[col]=frame[col].astype('float64')
    return frame


class LongTables:
    def __init__(self, folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.writers={};self.schemas={};self.counts={}

    def append(self, name, frame):
        if frame.empty: return
        frame=normalize(frame)
        table=pa.Table.from_pandas(frame,preserve_index=False)
        if name not in self.writers:
            schema=table.schema.remove_metadata()
            self.schemas[name]=schema
            self.writers[name]=pq.ParquetWriter(self.folder/(name+'.parquet'),schema,compression='zstd',use_dictionary=True)
            self.counts[name]=0
        schema=self.schemas[name]
        if set(table.column_names)!=set(schema.names):
            raise AssertionError('长表列变化: '+name+' '+str(set(table.column_names)^set(schema.names)))
        table=table.select(schema.names).cast(schema)
        self.writers[name].write_table(table,row_group_size=10000)
        self.counts[name]+=len(frame)

    def close(self):
        for writer in self.writers.values(): writer.close()


def attach_metadata(frame, metadata):
    frame=frame.copy()
    for key,value in metadata.items(): frame[key]=value
    return frame
