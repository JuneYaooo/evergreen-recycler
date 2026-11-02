#!/usr/bin/env bash
# 复现 Evals V2（v0.3.0）全部脚本层产物：在仓库根目录执行 bash evals/scripts/run_v2.sh
set -euo pipefail
R=evals/runs_v2
F=evals/fixtures
S=scripts/build_schedule.py
A=(--as-of 2026-09-19)
mkdir -p "$R"
python3 "$S" "$F/posts_main_v1.csv" "${A[@]}" -o "$R/main_schedule.md" --csv "$R/main_schedule.csv" --json "$R/main_summary.json"
python3 "$S" "$F/posts_main_v1.csv" "${A[@]}" --ledger "$F/ledger_v1.json" -o "$R/ledger_schedule.md" --csv "$R/ledger_schedule.csv" --json "$R/ledger_summary.json"
python3 "$S" "$F/posts_all_losers_v1.csv" "${A[@]}" -o "$R/all_losers_report.md" --csv "$R/all_losers_schedule.csv" --json "$R/all_losers_summary.json"
python3 "$S" "$F/posts_cold_start_v1.csv" "${A[@]}" -o "$R/cold_start_report.md" --json "$R/cold_start_summary.json"
python3 "$S" "$F/posts_metric_v1.csv" "${A[@]}" --metric total -o "$R/metric_total_report.md" --csv "$R/metric_total.csv" --json "$R/metric_total_summary.json"
python3 "$S" "$F/posts_metric_v1.csv" "${A[@]}" --metric per_day -o "$R/metric_perday_report.md" --csv "$R/metric_perday.csv" --json "$R/metric_perday_summary.json"
python3 "$S" "$F/posts_logic_v2.csv" "${A[@]}" -o "$R/logic_schedule.md" --csv "$R/logic_schedule.csv" --json "$R/logic_summary.json"
python3 "$S" "$F/posts_logic_v2.csv" "${A[@]}" --baseline rolling -o "$R/logic_rolling.md" --csv "$R/logic_rolling.csv" --json "$R/logic_rolling_summary.json"
python3 "$S" "$F/posts_logic_v2.csv" "${A[@]}" --min-sample 15 -o "$R/logic_minsample15.md" --json "$R/logic_minsample15_summary.json"
for i in a b; do
  python3 "$S" "$F/posts_main_v1.csv" "${A[@]}" --ledger "$F/ledger_v1.json" -o "$R/det_$i.md" --csv "$R/det_$i.csv" --json "$R/det_$i.json"
done
(cd "$R" && shasum -a 256 det_a.md det_a.csv det_a.json det_b.md det_b.csv det_b.json > determinism_sha256.txt)
