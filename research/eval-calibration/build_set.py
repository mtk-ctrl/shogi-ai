#!/usr/bin/env python3
"""Build the 'advantage that did not hold' position set from KUMOJI's own Floodgate games.

illusion: KUMOJI saw >= +300 at ply 20-80 in a game it LOST, and later fell to <= -300.
true:     KUMOJI saw >= +300 at ply 20-80 in a game it WON.
Up to 3 positions per game (first, middle, last of the qualifying span).
"""
import csv, sys, collections
src, out = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src, encoding="utf-8"), delimiter="\t"))
games = collections.defaultdict(list)
for r in rows:
    games[r["game_id"]].append(r)
sel = []
for gid, ms in games.items():
    ms.sort(key=lambda r: int(r["ply"]))
    res = ms[0]["result"]
    adv = [r for r in ms if 20 <= int(r["ply"]) <= 80 and 300 <= int(r["eval_ours"]) < 20000]
    if not adv:
        continue
    if res == "lose":
        later = [r for r in ms if int(r["ply"]) > int(adv[0]["ply"]) and int(r["eval_ours"]) <= -300]
        if not later:
            continue
        collapse = int(later[0]["ply"])
        adv = [r for r in adv if int(r["ply"]) < collapse]
        label = "illusion"
    elif res == "win":
        label = "true"
    else:
        continue
    picks = {0, len(adv) // 2, len(adv) - 1}
    for i in sorted(picks):
        r = adv[i]
        sel.append([label, gid, r["opponent"], r["side"], r["ply"], r["eval_ours"], r["depth"], r["usi"], r["sfen"]])
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["label", "game_id", "opponent", "side", "ply", "eval_ours", "depth", "played", "sfen"])
    w.writerows(sel)
c = collections.Counter(s[0] for s in sel)
print(out, dict(c), "games", len({(s[0], s[1]) for s in sel}))
