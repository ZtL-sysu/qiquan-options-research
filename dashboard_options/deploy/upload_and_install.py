"""Upload the private package over existing encrypted PSRP and install it."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[2] / "000656_dashboard"))
from remote_psrp import client, run

def main():
    package=ROOT.parents[2]/".private/options-dashboard-windows.zip"
    receipt=json.loads((ROOT/"deploy/package_receipt.json").read_text())
    if hashlib.sha256(package.read_bytes()).hexdigest()!=receipt["sha256"]: raise ValueError("package checksum changed")
    c=client(); run(c,"New-Item -ItemType Directory -Force C:\\OptionsDashboard | Out-Null")
    c.copy(str(package),"C:\\OptionsDashboard\\package.zip")
    remote=run(c,"(Get-FileHash C:\\OptionsDashboard\\package.zip -Algorithm SHA256).Hash.ToLower()").strip()
    if remote!=receipt["sha256"]: raise ValueError("remote checksum mismatch")
    run(c,r"""$ErrorActionPreference='Stop'
Expand-Archive C:\OptionsDashboard\package.zip -DestinationPath C:\OptionsDashboard -Force
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OptionsDashboard\app\deploy\windows\install.ps1
""")
    print(json.dumps({"status":"installed","sha256":remote},ensure_ascii=False))
if __name__=="__main__": main()
