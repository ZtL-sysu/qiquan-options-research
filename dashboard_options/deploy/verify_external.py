"""Check both the new /options/ path and the existing root page after deploy."""
from __future__ import annotations
import json, requests
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE="https://8.155.134.13"
def get(path):
    r=requests.get(BASE+path,timeout=20,verify=False,allow_redirects=True)
    return {"path":path,"status":r.status_code,"content_type":r.headers.get("content-type"),"bytes":len(r.content)}
def main():
    requests.packages.urllib3.disable_warnings()
    checks=[get("/"),get("/options/"),get("/options/latest.json"),get("/options/strategy/CC_OTM02_DTE60_R10_C75.html"),get("/options/gjdata/config.txt")]
    if any(x["status"]!=200 for x in checks[:4]) or checks[-1]["status"]!=404: raise SystemExit(json.dumps(checks,ensure_ascii=False))
    (ROOT/"deploy/external_verification.json").write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    print(json.dumps(checks,ensure_ascii=False))
if __name__=="__main__": main()
