# -*- coding: utf-8 -*-
"""
Render social-preview-template.html to social-preview.png (1280x640).

    python .github/render_social_preview.py

Uses headless Chrome or Edge so the card is drawn in Segoe UI, matching the Career
Impact Dashboard card it is designed alongside.

GitHub does not read this file from the repo. After rendering, upload it by hand:
    repo Settings > General > Social preview > Edit > Upload an image
Then refresh any cached LinkedIn card at linkedin.com/post-inspector/ .
"""
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "social-preview-template.html")
OUT = os.path.join(HERE, "social-preview.png")
W, H = 1280, 640

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    browser = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not browser:
        sys.exit("No Chrome or Edge found; add its path to BROWSERS.")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=%d,%d" % (W, H),
                    "--default-background-color=0d0d0dff", "--screenshot=" + out,
                    "file:///" + TEMPLATE.replace("\\", "/")],
                   check=True, capture_output=True, timeout=60)
    im = Image.open(out).convert("RGB")
    if im.size != (W, H):
        im = im.crop((0, 0, W, H))
    im.save(out, optimize=True)
    print("rendered %s  %dx%d  (%d bytes)" % (out, im.size[0], im.size[1], os.path.getsize(out)))
    print("NEXT: upload it at repo Settings > General > Social preview (GitHub ignores the repo file).")


if __name__ == "__main__":
    main()
