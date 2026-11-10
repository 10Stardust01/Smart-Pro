"""Bounded, offline accessibility smoke: static markup and primary CSS tokens.

Does not claim WCAG compliance, screen-reader, dynamic form, or mobile
browser acceptance. Run with the real Chromium role smoke for fuller coverage.
"""
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/styles.css").read_text(encoding="utf-8")
APP = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "backend/smartpro/reviewer_auth.py").read_text(encoding="utf-8")


class LandmarkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.skip = False
        self.dialog_label = False
        self.html_lang = False

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if props.get("id"):
            self.ids.append(props["id"])
        if tag == "html" and props.get("lang"):
            self.html_lang = True
        if tag == "a" and props.get("href") == "#main":
            self.skip = True
        if tag == "dialog" and props.get("aria-labelledby") == "confirmation-title":
            self.dialog_label = True


def luminance(hex_rgb):
    if re.fullmatch(r"#[0-9a-fA-F]{3}", hex_rgb):
        hex_rgb = "#" + "".join(c * 2 for c in hex_rgb[1:])
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", hex_rgb), hex_rgb
    values = [int(hex_rgb[i:i+2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in values]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def ratio(a, b):
    lum_a, lum_b = luminance(a), luminance(b)
    return (max(lum_a, lum_b) + .05) / (min(lum_a, lum_b) + .05)


def main():
    parser = LandmarkParser()
    parser.feed(HTML)
    assert parser.html_lang, "Document language missing"
    assert parser.skip and 'id="main"' in APP, "Skip-to-workspace target missing"
    assert parser.dialog_label and "confirmation-title" in parser.ids
    assert len(set(parser.ids)) == len(parser.ids), "Duplicate static document IDs"
    assert ":focus-visible" in CSS and ".skip:focus" in CSS
    assert 'aria-current="page"' in APP, "Active navigation announcement missing"
    assert "aria-busy" in APP and 'aria-label="Main navigation"' in APP
    assert 'for="username"' in AUTH and 'for="password"' in AUTH
    assert 'type="password"' in AUTH and '<h1>Sign in' in AUTH

    definitions = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)\s*;", CSS))
    for foreground in ("ink", "muted", "accent"):
        color = definitions[foreground]
        for background in ("surface", "white"):
            assert ratio(color, definitions[background]) >= 4.5, (
                foreground, background, ratio(color, definitions[background])
            )
    assert ratio(definitions["focus"], definitions["white"]) >= 3.0
    print("PASS: static language, skip link, dialog label, navigation, form labels, "
          "keyboard focus, and primary WCAG AA text-contrast color pairs")
    print("SCOPE: static source-contract smoke ONLY; not a WCAG audit")


if __name__ == "__main__":
    main()
