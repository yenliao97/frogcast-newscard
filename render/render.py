"""Taiwan Frogcast carousel renderer. One post = one spec.json -> 1080x1350 JPEGs (01.jpg ...).
Text is always typeset here (brand fonts/colours), never drawn by an image model.
Colours: twfrogcast-brand-docs/01-media-kit/assets/text/colours.txt · fonts: twfrogcast-web/styles.css :root.
Usage: python3 render.py <post_folder>   (reads <post_folder>/spec.json, image paths relative to it)
spec keys: bg (watercolour image, relative path) · wash (0-1 light overlay for legibility, default .35) · show_series (default off)"""
import json, os, re, subprocess, sys, html
HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")  # newscard 用 Playwright，不走這裡；這份只為了 import card_html
W, H = 1080, 1350
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,SOFT,wght@9..144,40,500;9..144,40,700&family=Inter:wght@400;500;600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;overflow:hidden}
body{position:relative;background:#ECECE1 url('BGIMG') center/cover;font-family:Inter,sans-serif;color:#33332F}
.wash{position:absolute;inset:0;background:#F6F5EE;opacity:WASH;z-index:0}
body::before{content:'';position:absolute;inset:0;background:url('PAPER') center/cover;opacity:.22;mix-blend-mode:multiply;z-index:0}
.label{position:absolute;top:56px;left:64px;display:flex;align-items:center;gap:16px;font:600 24px Inter;letter-spacing:.14em;text-transform:uppercase;color:#4F8083;z-index:5}
.label img{width:52px;height:52px}
.page{position:absolute;bottom:50px;right:64px;font:600 26px Inter;color:#565454;z-index:5}
.watermark{position:absolute;top:44px;right:48px;width:96px;height:96px;z-index:6}
.source{position:absolute;bottom:50px;left:64px;right:180px;font:400 24px/1.35 Inter;color:#565454;z-index:5}
.kapa{position:absolute;z-index:4;filter:drop-shadow(0 10px 18px rgba(51,51,47,.12))}
h1,h2{font-family:Fraunces,Georgia,serif;font-variation-settings:'SOFT' 40;font-weight:700;color:#33332F;letter-spacing:-.01em}
.hl{background:linear-gradient(transparent 58%,#D6F18B 58%)}
/* cover */
.scene{position:absolute;inset:0 0 330px 0;background-size:cover;background-position:center;z-index:1}
.scene.edge-round{border-radius:0 0 48px 48px;box-shadow:0 8px 24px rgba(51,51,47,.10)}
.scene.edge-line{border-bottom:10px solid #4F8083}
.scenefade{position:absolute;left:0;right:0;top:880px;height:140px;background:linear-gradient(rgba(246,245,238,0),rgba(246,245,238,.92));z-index:1}
.cover h1{position:absolute;left:64px;right:200px;bottom:108px;font-size:78px;line-height:1.02;z-index:2}
.cover .icon{position:absolute;right:64px;top:1052px;width:112px;height:112px;z-index:3}
.cover .sub{position:absolute;left:64px;bottom:58px;font:500 28px Inter;color:#4F8083;z-index:2}
/* answer */
.kicker{font:600 30px Inter;letter-spacing:.1em;text-transform:uppercase;color:#4F8083;margin-bottom:24px}
.answer{position:absolute;left:64px;right:64px;top:150px}
.answer h2{font-size:84px;line-height:1.04;margin-bottom:40px}
.answer p{font:500 50px/1.4 Inter;max-width:952px}
/* fact */
.fact{position:absolute;left:64px;right:64px;top:130px}
.fact .big{font-family:Fraunces,serif;font-weight:700;font-size:220px;line-height:.9;color:#4F8083}
.fact h2{font-size:70px;line-height:1.06;margin:20px 0 24px}
.fact p{font:500 48px/1.4 Inter;max-width:640px}
.element{position:absolute;z-index:3}
/* end */
.end{position:absolute;left:64px;right:64px;top:200px;text-align:center}
.end h2{font-size:84px;line-height:1.04;margin-bottom:28px}
.end p{font:500 34px/1.4 Inter;color:#565454}
.endimg{position:absolute;inset:0;text-align:center}
.endimg h2{position:absolute;left:64px;right:64px;top:84px;font-size:72px;line-height:1.05}
.endimg img{position:absolute;left:60px;right:60px;bottom:110px;width:960px;height:960px;object-fit:cover;border-radius:40px;box-shadow:0 10px 30px rgba(51,51,47,.14)}
"""
def img(src, base):
    return "file://" + os.path.abspath(os.path.join(base, src))
def card_html(c, i, n, spec, base):
    kind = c["type"]; e = html.escape
    parts = ['<div class="wash"></div>']
    if c.get("bg"):  # card-level background overrides the post background (cover uses bg/pond-cover.jpg)
        parts.insert(0, f'<div style="position:absolute;inset:0;background:url({img(c["bg"],base)}) center/cover;z-index:0"></div>')
    if spec.get("show_series"):  # off by default: Yen 2026-09-16 dropped the top-left series label
        parts.append(f'<div class="label"><img src="file://{HERE}/mark.png">{e(spec.get("series",""))}</div>')
    if kind == "cover":
        edge = c.get("edge", spec.get("cover_edge", "fade"))   # Yen 17:31: rounded corners joined the title band badly
        parts.append(f'<div class="scene edge-{edge}" style="background-image:url({img(c["scene"],base)});background-position:{c.get("scene_pos","center")}"></div>')
        if edge == "fade":
            parts.append('<div class="scenefade"></div>')  # scene_pos: Kapa standing low in a portrait scene gets cut by the centred crop (post 1, 2026-09-16)
        parts.append(f'<div class="cover"><h1>{c["title"]}</h1><div class="sub">{e(c.get("sub",""))}</div><img class="icon" src="file://{HERE}/icon.png"></div>')
    elif kind == "answer":
        parts.append(f'<div class="answer" style="{c.get("block_style","")}"><div class="kicker">{e(c.get("kicker","The short answer"))}</div><h2 style="{c.get("title_style","")}">{c["title"]}</h2><p style="{c.get("body_style","")}">{c["body"]}</p></div>')
    elif kind == "fact":
        parts.append(f'<div class="fact" style="{c.get("block_style","")}"><div class="big" style="{c.get("big_style","")}">{e(c["big"])}</div><h2 style="{c.get("title_style","")}">{c["title"]}</h2><p style="{c.get("body_style","")}">{c["body"]}</p></div>')
    elif kind == "end":
        parts.append(f'<div class="end" style="{c.get("block_style","")}"><h2 style="{c.get("title_style","")}">{c["title"]}</h2><p style="{c.get("body_style","")}">{c.get("body","")}</p></div>')
    elif kind == "end_image":
        parts.append(f'<div class="endimg"><h2>{c["title"]}</h2><img src="{img(c["image"],base)}"></div>')
    for el in c.get("elements", []):
        parts.append(f'<img class="element" src="{img(el["src"],base)}" style="{el["style"]}">')
    if c.get("kapa"):
        parts.append(f'<img class="kapa" src="{img(c["kapa"]["src"],base)}" style="{c["kapa"]["style"]}">')
    if c.get("source"):
        parts.append(f'<div class="source">Source: {e(c["source"])}</div>')
    if kind != "cover":
        parts.append(f'<img class="watermark" src="file://{HERE}/icon.png">')
    if n > 1:  # single-card posts (Yen 2026-09-17) have no 1/1 counter
        parts.append(f'<div class="page">{i}/{n}</div>')
    font = spec.get("body_font", "Inter")
    css = re.sub(r'(?<!family=)\bInter\b', '"' + font + '"', CSS).replace("family=Inter:wght", "family=" + font.replace(" ", "+") + ":wght")
    css = css.replace("PAPER", "file://" + HERE + "/paper.jpg").replace("BGIMG", ("file://" + os.path.join(base, spec["bg"])) if spec.get("bg") else "").replace("WASH", str(spec.get("wash", 0.35)))
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>{"".join(parts)}</body></html>'
def main(folder):
    folder = os.path.abspath(folder); spec = json.load(open(os.path.join(folder, "spec.json")))
    work = os.path.join(folder, "_render"); os.makedirs(work, exist_ok=True)
    cards = spec["cards"]
    for i, c in enumerate(cards, 1):
        h = os.path.join(work, f"{i:02d}.html"); open(h, "w").write(card_html(c, i, len(cards), spec, folder))
        png = os.path.join(work, f"{i:02d}.png")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                        f"--window-size={W},{H}", "--virtual-time-budget=8000", f"--screenshot={png}", "file://" + h],
                       capture_output=True, check=True)
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92", png, "--out", os.path.join(folder, f"{i:02d}.jpg")], capture_output=True, check=True)
        print("rendered", f"{i:02d}.jpg")
if __name__ == "__main__":
    main(sys.argv[1])
