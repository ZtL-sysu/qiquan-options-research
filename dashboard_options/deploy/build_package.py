"""Create a credential-free Windows deployment archive for /options/."""
from __future__ import annotations
import hashlib, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT.parents[2] / ".private"
PACKAGE = PRIVATE / "options-dashboard-windows.zip"

def main():
    PRIVATE.mkdir(exist_ok=True); PRIVATE.chmod(0o700)
    manifest=[]
    with zipfile.ZipFile(PACKAGE, "w", zipfile.ZIP_DEFLATED) as z:
        def add(source, target):
            z.write(source, target)
            manifest.append({"path":target,"sha256":hashlib.sha256(source.read_bytes()).hexdigest()})
        for name in ["data_backend.py", "update.py", "README.md"]:
            add(ROOT/name, "app/"+name)
        for source in (ROOT/"data").rglob("*"):
            if source.is_file(): add(source, "app/data/"+str(source.relative_to(ROOT/"data")).replace("\\","/"))
        for source in (ROOT/"templates").rglob("*"):
            if source.is_file(): add(source, "app/templates/"+str(source.relative_to(ROOT/"templates")).replace("\\","/"))
        for source in (ROOT/"deploy/windows").rglob("*"):
            if source.is_file(): add(source, "app/deploy/windows/"+source.name)
        z.writestr("package-manifest.json", json.dumps({"files":manifest,"contains_credentials":False},ensure_ascii=False,indent=2))
    PACKAGE.chmod(0o600)
    receipt={"archive":str(PACKAGE),"bytes":PACKAGE.stat().st_size,"sha256":hashlib.sha256(PACKAGE.read_bytes()).hexdigest(),"files":len(manifest),"contains_credentials":False}
    (ROOT/"deploy/package_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(receipt,ensure_ascii=False))

if __name__ == "__main__": main()
