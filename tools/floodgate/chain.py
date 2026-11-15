#!/usr/bin/env python3
"""Floodgate常時参加の「自分で次を起動する」判断（連鎖）。

GitHubの定期起動(schedule)は遅れたり飛ばされたりする（2026-11-15に常時参加の定期起動が3回続けて動かなかった）。
そこで、各回の最後にこの判断を呼び、続けてよければ同じworkflowをworkflow_dispatchで起動する。定期起動は予備として残す。

判断だけを行う純粋な関数と、CLIを分ける。CLIは判断をJSONで標準出力へ出し、起動はworkflow側のghが行う。
止め方: continuous.json の enabled を false にする（次の連鎖から止まる）、または実行中のrunを取り消す（取り消しでは連鎖しない）。
"""
import argparse
import datetime
import json
import sys

MAX_CONSECUTIVE_FAILURES = 3


def decide(cfg, *, mode, continuous, outcome, fail_count, now_utc):
    """次を起動するか決める。戻り値は dict(dispatch, next_fail_count, reason)。"""
    if continuous not in ("yes", "selftest"):
        return dict(dispatch=False, next_fail_count=0, reason="not a continuous run")
    if continuous == "selftest":
        # 配線確認用: probeを1回だけ連鎖させ、連鎖先はcontinuous=noにして止める
        ok = outcome == "success"
        return dict(dispatch=ok, next_fail_count=0, reason="selftest chain" if ok else "selftest run failed")
    if not cfg.get("enabled"):
        return dict(dispatch=False, next_fail_count=0, reason="continuous.json enabled=false")
    jst = now_utc + datetime.timedelta(hours=9)
    paused = set(cfg.get("pause_dates_jst", []))
    # 次の回は最長でsession_minutes後まで続くので、今日と終了時点の日付の両方を見る（workflowの判定と同じ）
    horizon = jst + datetime.timedelta(minutes=int(cfg.get("session_minutes", 210)))
    if {jst.strftime("%Y-%m-%d"), horizon.strftime("%Y-%m-%d")} & paused:
        return dict(dispatch=False, next_fail_count=0, reason="paused date in next session")
    if outcome == "success":
        return dict(dispatch=True, next_fail_count=0, reason="session finished; start next")
    nxt = fail_count + 1
    if nxt > MAX_CONSECUTIVE_FAILURES:
        return dict(dispatch=False, next_fail_count=nxt, reason=f"{nxt} consecutive failures; stop chain")
    return dict(dispatch=True, next_fail_count=nxt, reason=f"run did not succeed ({outcome}); retry {nxt}/{MAX_CONSECUTIVE_FAILURES}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--continuous", required=True)
    p.add_argument("--outcome", required=True, help="outcome of the live (or probe) step: success/failure/skipped")
    p.add_argument("--fail-count", type=int, default=0)
    a = p.parse_args(argv)
    cfg = json.load(open(a.config, encoding="utf-8"))
    r = decide(cfg, mode=a.mode, continuous=a.continuous, outcome=a.outcome, fail_count=a.fail_count,
               now_utc=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    json.dump(r, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
