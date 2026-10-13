#!/usr/bin/env python3
"""holo_push.py — 把 /tmp/holo/{sh*,sz*} 文件夹推到 GitHub org1/stocks-holo + 同步GitCode
段位登记 REGISTRY.json (拉线上merge自己的段, 不碰别人).
"""
import json, subprocess, base64, os, sys, glob

ORG = "jiegengxiangjianxue1"
REPO = "stocks-holo"
OUT = "/tmp/holo"

def creds():
    line = [l for l in open("/home/agentuser/.git-credentials").read().strip().splitlines() if "github.com" in l][0]
    return line.split(":")[2].split("@")[0]

TOK = creds()
def gh(path, method="GET", data=None):
    cmd = ["curl", "-sf", "--retry", "5", "--retry-delay", "2", "--retry-all-errors",
           "-X", method, "-H", f"Authorization: token {TOK}", "-H", "Accept: application/vnd.github+json"]
    if data is not None:
        cmd += ["-d", json.dumps(data)]
    r = subprocess.run(cmd + [f"https://api.github.com{path}"], capture_output=True, text=True, timeout=90)
    return json.loads(r.stdout) if r.stdout else {}

def main():
    br = gh(f"/repos/{ORG}/{REPO}/git/ref/heads/main")
    if not br:
        print("仓库空, 需先建首commit"); sys.exit(1)
    base_commit = gh(f"/repos/{ORG}/{REPO}/commits/" + br["object"]["sha"])
    tree_sha = base_commit["commit"]["tree"]["sha"]
    tree = gh(f"/repos/{ORG}/{REPO}/git/trees/{tree_sha}?recursive=1")
    existing = {t["path"] for t in tree.get("tree", [])}

    # REGISTRY: 拉线上merge
    reg = {}
    if "REGISTRY.json" in existing:
        b = gh(f"/repos/{ORG}/{REPO}/contents/REGISTRY.json")
        reg = json.loads(base64.b64decode(b["content"]).decode())
    agent = os.environ.get("HOLO_AGENT", "master-qwerzxcva")
    seg = {"agent": agent, "ts": base_commit["commit"]["committer"]["date"]}
    reg.setdefault("segments", [])
    if not any(s["agent"] == agent for s in reg["segments"]):
        reg["segments"].append(seg)

    # 组tree变更
    entries = []
    files = [f for f in glob.glob(f"{OUT}/*/*") if os.path.isfile(f)]
    files.append(f"{OUT}/REGISTRY.json.tmp")
    json.dump(reg, open(f"{OUT}/REGISTRY.json.tmp", "w"), ensure_ascii=False, indent=1)
    n_new, n_skip = 0, 0
    for f in files:
        path = os.path.relpath(f, OUT).replace("\\", "/")
        if path == "REGISTRY.json.tmp": path = "REGISTRY.json"
        sha = gh(f"/repos/{ORG}/{REPO}/contents/{path}")  # 简单策略: 已存在即跳过(merge语义由collect端保证)
        if path != "REGISTRY.json" and sha.get("sha"):
            n_skip += 1
            continue
        content = base64.b64encode(open(f, "rb").read()).decode()
        r = gh(f"/repos/{ORG}/{REPO}/contents/{path}", "PUT",
               {"message": f"holo: {path}", "content": content, "branch": "main"})
        if r.get("commit"):
            n_new += 1
        else:
            print("PUT fail", path, str(r)[:80])
    print(f"推送完成: 新增{n_new} 跳过(已存在){n_skip}")
    os.remove(f"{OUT}/REGISTRY.json.tmp")

if __name__ == "__main__":
    main()
