from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from covered_call.reporting import report

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    last=json.loads((ROOT/'outputs/milestone2/latest_run.json').read_text(encoding='utf-8'))
    report(ROOT/'outputs/milestone2'/last['run_id'])
