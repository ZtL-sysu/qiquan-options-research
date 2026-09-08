import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from covered_call.data import sync

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='仅同步510050及其期权历史数据')
    parser.add_argument('--refresh',action='store_true',help='重新下载全部年份，接收早期历史修订')
    args=parser.parse_args()
    try:
        sync(args.refresh)
    except Exception as exc:
        # pymysql异常可能含服务器/用户名，不打印原始连接异常。
        if type(exc).__module__.startswith('pymysql'):
            print('数据库失败，错误类型:',type(exc).__name__,'错误码:',exc.args[0])
        else:
            raise
        sys.exit(1)
