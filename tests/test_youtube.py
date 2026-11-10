"""python3 -m unittest discover -s ~/.claude/skills/youtube-insights/tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "scripts"
FIX = Path(__file__).parent / "fixtures"


def run(*a):
    return subprocess.run([sys.executable, *map(str, a)], check=True, capture_output=True, text=True).stdout


def fake(n=12):
    vids = []
    for i in range(n):
        views = [450, 460, 1400, 430, 20, 470, 1300, 440, 480, 420, 30, 455][i % 12]
        vids.append({"id": f"vid{i:08d}", "title": ("POR QUE O FATO %d ACONTECEU? #Historia" if i % 2 == 0 else "O FATO %d — 1900") % i,
                     "description": "Imagine um fato fictício." if i % 3 else "Em 1940, um fato fictício.",
                     "published_at": f"2026-11-{1 + i // 2:02d}T00:00", "time_known": False, "format": "short",
                     "duration_s": 80 + i, "views": views, "avg_view_s": 60, "avg_pct": .7, "stayed": .6 if views > 1000 else .5,
                     "subs": views // 300, "impressions": 100, "ctr": .03, "likes": views // 20, "comments": 0, "shares": 0,
                     "watch_time_s": views * 60})
    return vids


class T(unittest.TestCase):
    def test_collect(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "v.json"
            run(S / "collect_parse.py", "--analytics", FIX / "analytics.json", "--content", f"short:{FIX / 'content.txt'}",
                "--ids", FIX / "ids.txt", "--collected-at", "2026-11-10T12:00", "--out", out)
            v = {x["id"]: x for x in json.loads(out.read_text())["videos"]}
            self.assertEqual(set(v), {"AAAAAAAAAA1", "BBBBBBBBBB2"})
            a = v["AAAAAAAAAA1"]
            self.assertEqual(a["views"], 1280)
            self.assertAlmostEqual(a["stayed"], .601)
            self.assertEqual(a["avg_view_s"], 65)
            self.assertEqual(a["published_at"], "2026-11-09T00:00")
            self.assertTrue(a["description"].startswith("Imagine"))
            b = v["BBBBBBBBBB2"]  # título com "|" e linha separada por TAB
            self.assertEqual(b["views"], 40)
            self.assertEqual(b["duration_s"], 58)
            self.assertEqual(b["url"], "https://www.youtube.com/shorts/BBBBBBBBBB2")

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "v.json").write_text(json.dumps({"channel": "x", "collected_at": "2026-11-10T12:00", "videos": fake()}))
            run(S / "tag_videos.py", "--posts", d / "v.json", "--out", d / "t.json")
            tags = json.loads((d / "t.json").read_text())["tags"]
            self.assertEqual({t["title_format"] for t in tags}, {"Pergunta (POR QUE / COMO…?)", "Nome + ano/série"})
            self.assertNotIn("_default", {t["region"] for t in tags})
            ig = {"posts": [{"id": "ig1", "published_at": "2026-11-01T10:00", "views": 900, "hook": "O fato 0 em 1900", "caption": "fato fictício 1900 historia"}]}
            (d / "ig.json").write_text(json.dumps(ig))
            run(S / "analyze.py", "--videos", d / "v.json", "--tags", d / "t.json", "--cross", d / "ig.json", "--out", d / "a.json")
            a = json.loads((d / "a.json").read_text())
            self.assertEqual(a["summary"]["hits"], 2)
            self.assertEqual(a["summary"]["flops"], 2)
            self.assertEqual(a["dimensions"]["title_format"][0]["group"], "Pergunta (POR QUE / COMO…?)")
            self.assertTrue(any(f["id"] == "stayed" for f in a["findings"]))
            run(S / "render_report.py", "--analysis", d / "a.json", "--out", d / "r.html")
            html = (d / "r.html").read_text()
            self.assertTrue(html.startswith("<title>YouTube"))
            self.assertIn("Continuaram assistindo", html)


if __name__ == "__main__":
    unittest.main()
