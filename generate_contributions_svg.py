#!/usr/bin/env python3
"""
Regenerates panel-contributions.svg from live GitHub contribution data.

Requires:
  - GH_USERNAME   env var: the GitHub username to fetch stats for
  - GH_TOKEN      env var: a token with access to the GraphQL contributionsCollection
                   field for that user (a classic PAT with the 'read:user' scope
                   works; the default Actions GITHUB_TOKEN does NOT have this scope)

Run: python3 scripts/generate_contributions_svg.py
Writes: panel-contributions.svg (overwrites in place)
"""

import os
import sys
import json
import datetime
import urllib.request

OUT_PATH = os.environ.get("OUT_PATH", "panel-contributions.svg")
GH_USERNAME = os.environ.get("GH_USERNAME")
GH_TOKEN = os.environ.get("GH_TOKEN")

GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contributions(username: str, token: str) -> dict:
    body = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": username}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "readme-stats-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if "errors" in payload:
        raise RuntimeError(f"GitHub GraphQL error: {payload['errors']}")
    return payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def build_svg(calendar: dict) -> str:
    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    # Flatten days, keep week index for the heatmap grid
    all_days = []
    for wi, week in enumerate(weeks):
        for day in week["contributionDays"]:
            all_days.append({
                "date": day["date"],
                "weekday": day["weekday"],   # 0=Sun .. 6=Sat
                "count": day["contributionCount"],
                "week_index": wi,
            })

    active_days = sum(1 for d in all_days if d["count"] > 0)

    week_totals = []
    for week in weeks:
        week_totals.append(sum(d["contributionCount"] for d in week["contributionDays"]))
    best_week = max(week_totals) if week_totals else 0

    # ---- line chart geometry (matches original card: x 32..768, y 140..210) ----
    chart_left, chart_right = 32.0, 768.0
    chart_top, chart_bottom = 140.0, 210.0
    n = len(week_totals)
    max_week = max(week_totals) if week_totals and max(week_totals) > 0 else 1

    points = []
    for i, wt in enumerate(week_totals):
        x = chart_left + (chart_right - chart_left) * (i / max(n - 1, 1))
        # more contributions -> higher on chart (smaller y). Flatten weeks with 0
        # toward the baseline like the original template did.
        frac = wt / max_week if max_week else 0
        y = chart_bottom - frac * (chart_bottom - chart_top)
        points.append((round(x, 1), round(y, 1)))

    line_path = " L ".join(f"{x} {y}" for x, y in points)
    area_path = f"M {line_path} L {points[-1][0]} {chart_bottom} L {points[0][0]} {chart_bottom} Z"
    line_only_path = f"M {line_path}"
    last_x, last_y = points[-1]

    # ---- month labels along the chart x-axis ----
    month_labels = []
    seen_months = set()
    for i, week in enumerate(weeks):
        first_day = week["contributionDays"][0]["date"]
        month = first_day[:7]  # YYYY-MM
        if month not in seen_months:
            seen_months.add(month)
            x = chart_left + (chart_right - chart_left) * (i / max(n - 1, 1))
            label = datetime.date.fromisoformat(first_day).strftime("%b")
            month_labels.append((round(x, 1), label))

    month_svg = "\n  ".join(
        f'<text x="{x}" y="242" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" '
        f'font-size="11" fill="#8b949e">{label}</text>'
        for x, label in month_labels
    )

    # ---- heatmap grid (7 rows x n columns), bucketed like GitHub's own shading ----
    counts_nonzero = sorted(d["count"] for d in all_days if d["count"] > 0)

    def bucket_color(count: int) -> str:
        if count == 0:
            return "#161b22"
        if not counts_nonzero:
            return "#161b22"
        # quartile thresholds relative to this user's own nonzero activity
        q1 = counts_nonzero[int(len(counts_nonzero) * 0.25)]
        q2 = counts_nonzero[int(len(counts_nonzero) * 0.50)]
        q3 = counts_nonzero[int(len(counts_nonzero) * 0.75)]
        if count <= q1:
            return "#3b4048"
        if count <= q2:
            return "#6e7681"
        if count <= q3:
            return "#b1bac4"
        return "#f0f6fc"

    cell = 9
    gap = 12
    grid_left = 46
    grid_top = 250

    rects = []
    for d in all_days:
        x = grid_left + d["week_index"] * gap
        y = grid_top + d["weekday"] * gap
        color = bucket_color(d["count"])
        rects.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}"/>')

    # scale the grid horizontally so it still spans x=32..768 regardless of week count
    grid_span = grid_left + (n - 1) * gap + cell
    target_span = chart_right - chart_left
    scale_x = (target_span - (chart_left + cell)) / max(grid_span - (chart_left + cell), 1)
    translate_x = round(chart_left - chart_left * scale_x, 4)

    rects_svg = "\n    ".join(rects)

    today_str = datetime.date.today().isoformat()

    svg = f'''<svg width="800" height="400" viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" width="799" height="399" rx="10" fill="#0d1117" stroke="#30363d" stroke-width="1"/>
  <rect x="0" y="0" width="800" height="34" rx="10" fill="#161b22"/>
  <rect x="0" y="18" width="800" height="16" fill="#161b22"/>
  <circle cx="20" cy="17" r="6" fill="#ff5f56"/>
  <circle cx="40" cy="17" r="6" fill="#ffbd2e"/>
  <circle cx="60" cy="17" r="6" fill="#27c93f"/>
  <text x="400" y="22" text-anchor="middle" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="12" fill="#8b949e">{GH_USERNAME}@github: ~/contributions</text>

  <text x="32" y="98" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="46" font-weight="700" fill="#f0f6fc">{total}</text>
  <text x="32" y="120" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="13" fill="#8b949e">contributions in the last year</text>
  <text x="768" y="70" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="22" font-weight="700" fill="#f0f6fc">{active_days}</text>
  <text x="768" y="86" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="12" fill="#8b949e">active days</text>
  <text x="768" y="112" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="22" font-weight="700" fill="#f0f6fc">{best_week}</text>
  <text x="768" y="128" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="12" fill="#8b949e">best week</text>

  <path d="{area_path}" fill="#f0f6fc" opacity="0.08"/>
  <path d="{line_only_path}" fill="none" stroke="#f0f6fc" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{last_x}" cy="{last_y}" r="3" fill="#f0f6fc"/>
  <line x1="32" y1="210" x2="768" y2="210" stroke="#30363d" stroke-width="1"/>

  {month_svg}

  <text x="36" y="270" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="10" fill="#8b949e">Mon</text>
  <text x="36" y="294" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="10" fill="#8b949e">Wed</text>
  <text x="36" y="318" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="10" fill="#8b949e">Fri</text>

  <g transform="translate({translate_x},0) scale({round(scale_x, 6)},1)">
    {rects_svg}
  </g>

  <text x="32" y="356" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="12" fill="#8b949e">{total} contributions in the last year</text>
  <text x="768" y="356" text-anchor="end" font-family="SFMono-Regular,Consolas,Menlo,Monaco,monospace" font-size="9" fill="#3b4048">updated {today_str}</text>
</svg>
'''
    return svg


def main():
    if not GH_USERNAME or not GH_TOKEN:
        print("GH_USERNAME and GH_TOKEN env vars are required.", file=sys.stderr)
        sys.exit(1)

    calendar = fetch_contributions(GH_USERNAME, GH_TOKEN)
    svg = build_svg(calendar)

    with open(OUT_PATH, "w") as f:
        f.write(svg)

    print(f"Wrote {OUT_PATH} ({calendar['totalContributions']} contributions)")


if __name__ == "__main__":
    main()
