"""Grava a composição quadro a quadro. Uso: gravar.py amostras t1 t2 ...  |  gravar.py video saida.mp4 [fps]"""
import subprocess, sys, os
from playwright.sync_api import sync_playwright
V = os.path.dirname(os.path.abspath(__file__)); URL = "file://" + os.path.join(V, "comp", "index.html")
modo = sys.argv[1]
with sync_playwright() as p:
    nav = p.chromium.launch(channel="chrome", headless=True)
    pg = nav.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto(URL); pg.evaluate("window.pronto")
    if modo == "amostras":
        os.makedirs(os.path.join(V, "amostras"), exist_ok=True)
        for t in sys.argv[2:]:
            pg.evaluate(f"renderAt({t})"); pg.screenshot(path=os.path.join(V, "amostras", f"t{float(t):06.1f}.png"))
    else:
        saida, fps = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 30
        dur = pg.evaluate("DUR"); n = int(dur * fps)
        ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
                               "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", saida],
                              stdin=subprocess.PIPE)
        for k in range(n):
            pg.evaluate(f"renderAt({k / fps})")
            ff.stdin.write(pg.screenshot(type="png"))
            if k % (fps * 10) == 0: print(f"{k / fps:.0f}s", flush=True)
        ff.stdin.close(); ff.wait(); print("ok", saida)
    nav.close()
