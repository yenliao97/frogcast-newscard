#!/usr/bin/env python3
"""newscard：外媒搬運 5🐸 的自動圖卡（Taiwan Frogcast）

雲端 routine 判定 5🐸 時，把一份卡片規格寫進 queue/<Threads 草稿 id>.json 並 push。
GitHub Actions 收到後跑這支：檢查規格 → 排版渲染（固定素材，不現生圖）→ 自己量有沒有溢出
→ 上傳 R2 → 圖掛進那兩則 Threads／X 草稿 → 另建一則英文 IG 草稿 → 規格搬到 done/。
任何一步失敗就整個停下來、什麼都不改：那兩則草稿維持純文字照常可發，GitHub 寄失敗通知給 Yen。

  python3 newscard.py process queue/<id>.json     正式跑（Actions 用）
  python3 newscard.py render  queue/<id>.json out/ 只渲染不上傳，本機預覽用
  python3 newscard.py selftest                    檢查 R2 與 Buffer 的金鑰能不能用

金鑰只從環境變數讀：R2_ACCOUNT_ID、R2_ACCESS_KEY_ID、R2_SECRET_ACCESS_KEY、BUFFER_API_KEY。
HTTP 一律走 curl，金鑰從 stdin 交給 curl，不出現在指令列。
2026-10-09 Kapa 建。正本與理由：FC Brand project-log 2026-10-09；版型來源 sc02（9/22，Yen 看過）。
"""
import datetime as dt
import html
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "render"))
from render import card_html, W, H  # noqa: E402

BUCKET = "hanna-media"
PUBLIC_BASE = "https://pub-2fc85598a2aa4a2e9af6ba8e8eaab2e3.r2.dev"
ORG = "6aa6f0671eec97abeae30615"
CHANNELS = {"threads": "6aa6f2d6ea19ca0bde374291", "twitter": "6aa6f457ea19ca0bde376b25",
            "instagram": "6aa6f249ea19ca0bde373613"}

THEMES = ["chip", "shipping", "coastguard", "air", "table", "podium", "document",
          "infowar", "cable", "energy", "islandchain", "handshake"]
# 2026-10-09 去背檢查：shipping_a 去背後滿畫面白點、cable_b／energy_b 是滿版場景 → 已從 repo 拿掉，固定用另一版。
# table 兩張都是滿版會議桌，去不了背 → 用圓角相框放（FRAMED）。
VARIANTS = {"cable": ["a"], "energy": ["a"], "shipping": ["b"]}
FRAMED = {"table"}
ART_STYLE = "width:330px;left:70px;bottom:80px"
FRAMED_STYLE = ("width:310px;height:310px;object-fit:cover;left:70px;bottom:104px;"
                "border-radius:28px;box-shadow:0 8px 22px rgba(51,51,47,.16)")
POSES = ["angry", "announce", "cheerful", "confused", "idea", "neutral", "pointing", "surprised"]
# 字數上限：照 sc02 那張的字量抓，超過就不會是一次到位的版面
# 2026-10-09 邊界測試：title 70／body 380／kapa_line 100 全滿時縮到 31px 還是壓到插畫 → 收緊到「全滿也排得下」
LIMITS = {"big": 24, "title": 60, "body": 320, "kapa_line": 80, "source": 48, "ig_caption": 1500}
BODY_SIZES = [37, 35, 33, 31]   # 放不下就一級一級縮，縮到 31 還放不下就失敗，不硬塞
BANNED = ["—", "我發現"]   # 破折號、假裝親身經歷：Yen 一眼就抓到的 AI 味


def die(msg):
    print(f"❌ {msg}")
    sys.exit(1)


# ---------- 規格 ----------

def validate(c):
    errs = []
    for k in ["threads_id", "x_id", "big", "title", "body", "kapa_line", "theme", "kapa", "source", "ig_caption"]:
        if not str(c.get(k, "")).strip():
            errs.append(f"缺 {k}")
    for k, n in LIMITS.items():
        if len(str(c.get(k, ""))) > n:
            errs.append(f"{k} {len(c[k])} 字元，上限 {n}")
    if c.get("theme") not in THEMES:
        errs.append(f"theme 要是 {THEMES} 之一，拿到 {c.get('theme')!r}")
    if c.get("variant", "a") not in ("a", "b"):
        errs.append("variant 只能是 a 或 b")
    if c.get("kapa") not in POSES:
        errs.append(f"kapa 要是 {POSES} 之一，拿到 {c.get('kapa')!r}")
    hl = c.get("highlight")
    if hl and hl not in c.get("body", ""):
        errs.append("highlight 必須是 body 裡一字不差的一段")
    for k in ["big", "title", "body", "kapa_line", "source", "ig_caption"]:
        for b in BANNED:
            if b in str(c.get(k, "")):
                errs.append(f"{k} 含禁用字 {b!r}")
    return errs


def art_variant(c):
    """要的那一版不能用，就換成能用的那一版（不失敗：這不是規格寫錯，是素材庫的限制）。"""
    v, ok = c.get("variant", "a"), VARIANTS.get(c["theme"], ["a", "b"])
    return v if v in ok else ok[0]


def build_spec(c, body_size):
    e = html.escape
    body = e(c["body"])
    if c.get("highlight"):
        body = body.replace(e(c["highlight"]), f"<span class='hl'>{e(c['highlight'])}</span>", 1)
    body += f"<br><br>🐸 <b>Kapa</b>: {e(c['kapa_line'])}"
    return {"bg": "render/bg/pond-portrait.jpg", "wash": 0.25, "body_font": "Lexend", "cards": [{
        "type": "fact", "big": c["big"], "big_style": "font-size:92px;line-height:1.0",
        "title": e(c["title"]), "body": body, "body_style": f"max-width:900px;font-size:{body_size}px",
        "elements": [{"src": f"art/library/{c['theme']}_{art_variant(c)}.png",
                      "style": FRAMED_STYLE if c["theme"] in FRAMED else ART_STYLE}],
        "kapa": {"src": f"art/kapa/kapa-{c['kapa']}.png", "style": "width:280px;right:70px;bottom:70px"},
        "source": c["source"]}]}


# ---------- 渲染 ----------

MEASURE = """() => {
  const r = s => document.querySelector(s).getBoundingClientRect();
  const fact = r('.fact'), big = document.querySelector('.fact .big');
  const tops = [...document.querySelectorAll('.element, .kapa')].map(x => x.getBoundingClientRect().top);
  const imgs = [...document.images].filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src);
  return {factBottom: fact.bottom, artTop: Math.min(...tops), bigOverflow: big.scrollWidth > big.clientWidth + 1,
          broken: imgs, fonts: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)};
}"""


def render(c, out_jpg):
    """排版、量尺寸、截圖。回傳實際用的內文字級。量到放不下就換小一級，全部放不下就失敗。"""
    from playwright.sync_api import sync_playwright
    from PIL import Image
    work = tempfile.mkdtemp(prefix="newscard-")
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": W, "height": H})
        for size in BODY_SIZES:
            spec = build_spec(c, size)
            h = os.path.join(work, f"card-{size}.html")
            open(h, "w", encoding="utf-8").write(card_html(spec["cards"][0], 1, 1, spec, HERE))
            page.goto("file://" + h, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            m = page.evaluate(MEASURE)
            if m["broken"]:
                die(f"圖片載不到：{m['broken']}")
            if "Lexend" not in m["fonts"] or "Fraunces" not in m["fonts"]:
                die(f"字型沒載到（{m['fonts']}），不能用備用字型出圖")
            if m["bigOverflow"]:
                die(f"大字「{c['big']}」超出一行寬度，請縮短")
            gap = m["artTop"] - m["factBottom"]
            print(f"內文 {size}px：文字底 {m['factBottom']:.0f}，插畫頂 {m['artTop']:.0f}，間距 {gap:.0f}")
            if gap >= 24:
                png = os.path.join(work, "card.png")
                page.screenshot(path=png)
                browser.close()
                Image.open(png).convert("RGB").save(out_jpg, "JPEG", quality=92)
                im = Image.open(out_jpg)
                if im.size != (W, H):
                    die(f"輸出尺寸 {im.size}，不是 {W}x{H}")
                return size
        browser.close()
    die(f"內文縮到 {BODY_SIZES[-1]}px 還是壓到插畫，請縮短 body 或 kapa_line")


# ---------- R2（S3 API） ----------

def env(k):
    v = os.environ.get(k, "").strip()
    if not v:
        die(f"環境變數 {k} 沒設")
    return v


def r2(method, path, file=None, ctype=None):
    acct = env("R2_ACCOUNT_ID")
    url = f"https://{acct}.r2.cloudflarestorage.com/{BUCKET}{path}"
    cmd = ["curl", "-s", "-S", "-w", "\n%{http_code}", "--aws-sigv4", "aws:amz:auto:s3", "-K", "-", "-X", method, url]
    if file:
        cmd[1:1] = ["-T", file, "-H", f"Content-Type: {ctype}"]
    conf = f'user = "{env("R2_ACCESS_KEY_ID")}:{env("R2_SECRET_ACCESS_KEY")}"\n'
    r = subprocess.run(cmd, input=conf, capture_output=True, text=True)
    body, _, code = r.stdout.rpartition("\n")
    return code.strip(), body


def upload(path, key):
    code, body = r2("PUT", "/" + key, path, "image/jpeg")
    if code != "200":
        die(f"R2 上傳失敗 HTTP {code}：{body[:300]}")
    url = f"{PUBLIC_BASE}/{key}"
    for _ in range(5):
        c = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url], capture_output=True, text=True).stdout
        if c == "200":
            return url
        time.sleep(3)
    die(f"公開網址打不開（HTTP {c}）：{url}")


# ---------- Buffer ----------

POST_FIELDS = """id status channelId channelService dueAt text assets { source }
  metadata { ... on InstagramPostMetadata { isAiGenerated } ... on ThreadsPostMetadata { topic } }"""


def buffer(query, variables):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"query": query, "variables": variables}, f, ensure_ascii=False)
        path = f.name
    try:
        r = subprocess.run(["curl", "-s", "-X", "POST", "https://api.buffer.com", "-H", "Content-Type: application/json",
                            "-H", "@-", "--data-binary", f"@{path}"],
                           input=f"Authorization: Bearer {env('BUFFER_API_KEY')}\n", capture_output=True, text=True)
    finally:
        os.unlink(path)
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        die(f"Buffer 回應不是 JSON：{r.stdout[:300]} {r.stderr[:300]}")
    if d.get("errors"):
        die(f"Buffer 回錯誤：{d['errors']}")
    return d["data"]


def get_post(pid):
    q = "query($id: PostId!) { post(input: {id: $id}) { %s } }" % POST_FIELDS
    p = buffer(q, {"id": pid}).get("post")
    if not p:
        die(f"讀不到貼文 {pid}")
    return p


def check_target(p, channel):
    if p["channelId"] != CHANNELS[channel]:
        die(f"{p['id']} 不是 Frogcast {channel} 頻道的貼文")
    if p["status"] not in ("draft", "scheduled"):
        die(f"{p['id']} 是 {p['status']}，已經發出或不能改，不碰（發出的貼文補不了圖）")
    if p["assets"]:
        die(f"{p['id']} 已經有 {len(p['assets'])} 張圖，不覆蓋")
    if not p["text"].startswith("🗞️") and channel == "threads":
        die(f"{p['id']} 不是外媒搬運的貼文（開頭不是 🗞️）")


def attach(p, channel, url):
    """editPost 會整則覆寫：文字、時間、狀態、Threads 主題都照原樣帶回去，只多一張圖。"""
    inp = {"id": p["id"], "text": p["text"], "assets": [{"image": {"url": url}}], "tagIds": [],
           "mode": "customScheduled", "dueAt": p["dueAt"], "saveToDraft": p["status"] == "draft",
           "schedulingType": "automatic"}
    topic = (p.get("metadata") or {}).get("topic")
    if channel == "threads":
        inp["metadata"] = {"threads": {"type": "post", **({"topic": topic} if topic else {})}}
    q = """mutation($input: EditPostInput!) { editPost(input: $input) {
      ... on PostActionSuccess { post { %s } } ... on MutationError { message } } }""" % POST_FIELDS
    res = buffer(q, {"input": inp})["editPost"]
    if "message" in res:
        die(f"Buffer 拒絕編輯 {p['id']}：{res['message']}")
    n = res["post"]
    if (n["status"], n["dueAt"], n["text"], [a["source"] for a in n["assets"]]) != (p["status"], p["dueAt"], p["text"], [url]):
        die(f"讀回不對 {n['id']}：{n['status']} {n['dueAt']} {len(n['assets'])} 張")
    print(f"✅ {channel} {n['id']}｜{n['status']}｜{n['dueAt']}｜已掛圖")
    return n


def create_ig(text, due, url):
    inp = {"channelId": CHANNELS["instagram"], "text": text, "schedulingType": "automatic", "mode": "customScheduled",
           "dueAt": due, "saveToDraft": True, "needsApproval": False, "assets": [{"image": {"url": url}}],
           "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True, "isAiGenerated": False}}}
    q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
      ... on PostActionSuccess { post { %s } } ... on MutationError { message } } }""" % POST_FIELDS
    res = buffer(q, {"input": inp})["createPost"]
    if "message" in res:
        die(f"Buffer 拒絕建 IG 草稿：{res['message']}")
    n = res["post"]
    print(f"✅ instagram {n['id']}｜{n['status']}｜{n['dueAt']}｜新草稿")
    return n


# ---------- 指令 ----------

def load(path):
    c = json.load(open(path, encoding="utf-8"))
    errs = validate(c)
    if errs:
        die("規格不合格：\n  - " + "\n  - ".join(errs))
    return c


def cmd_render(path, outdir):
    c = load(path)
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(path))[0] + ".jpg")
    size = render(c, out)
    print(f"🖼  {out}（內文 {size}px）")


def cmd_process(path):
    c = load(path)
    # 先確認兩則草稿都還能改，再做任何上傳：失敗時什麼都不留
    th, x = get_post(c["threads_id"]), get_post(c["x_id"])
    check_target(th, "threads")
    check_target(x, "twitter")
    out = os.path.join(tempfile.mkdtemp(), "01.jpg")
    size = render(c, out)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    url = upload(out, f"frogcast/news/{c['threads_id']}-{stamp}/01.jpg")
    print(f"已上傳：{url}")
    th2 = attach(th, "threads", url)
    x2 = attach(x, "twitter", url)
    ig = create_ig(c["ig_caption"], x["dueAt"], url)
    done = os.path.join(HERE, "done", os.path.basename(path))
    c["result"] = {"image": url, "body_px": size, "threads": th2["id"], "x": x2["id"], "instagram": ig["id"],
                   "instagram_due": ig["dueAt"], "done_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    json.dump(c, open(done, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.remove(path)
    print(f"📦 規格搬到 done/{os.path.basename(path)}")


def cmd_selftest():
    code, body = r2("GET", "?list-type=2&prefix=frogcast/&max-keys=1")
    print(f"R2 列出 frogcast/：HTTP {code}" + ("" if code == "200" else f"｜{body[:300]}"))
    flt ={"organizationId": ORG, "sort": [{"field": "dueAt", "direction": "desc"}],
           "filter": {"channelIds": [CHANNELS["threads"]], "status": ["sent"], "postTypes": []}}
    d = buffer("query($input: PostsInput!) { posts(first: 1, input: $input) { edges { node { id status } } } }", {"input": flt})
    n = d["posts"]["edges"]
    print(f"Buffer 讀 Frogcast Threads：OK（最近一則 {n[0]['node']['id'] if n else '無'}）")
    if code != "200":
        die("R2 金鑰不能用")
    print("✅ selftest 通過")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["process"] and len(a) == 2:
        cmd_process(a[1])
    elif a[:1] == ["render"] and len(a) == 3:
        cmd_render(a[1], a[2])
    elif a == ["selftest"]:
        cmd_selftest()
    else:
        print(__doc__)
        sys.exit(2)
