"""一条命令复核 Milestone 1；覆盖本目录审计输出，不写远程数据库。"""
import contextlib
from datetime import datetime
import importlib.util
import io
import sys

from audit_db import ROOT, TOOL, discover, save_json
from extract_evidence import extract
from profile_additional import profile
from validate_sample import validate


def main():
    spec = importlib.util.spec_from_file_location('gj_health', TOOL)
    toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(toolkit)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        toolkit.command_health(None)
    # 工具的健康检查成功输出只有库名和耗时，不含账号密码。
    save_json({'passed':True, 'checked_at':datetime.now().astimezone().isoformat(),
               'tool':'00_完整数据库工具包/01_机器运行文件/国金数据库取数.py',
               'result':captured.getvalue().strip()}, 'health_check.json')
    print(captured.getvalue().strip(),flush=True)
    discover()
    extract()
    profile()
    validate()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except Exception as exc:
        print('审计未完成:',type(exc).__name__,'错误码:',exc.args[0] if exc.args and isinstance(exc.args[0],int) else '未提供')
        sys.exit(1)
