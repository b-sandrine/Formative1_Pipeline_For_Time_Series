"""Task 4 forecast script.

Fetches readings from the Task 3 API, preprocesses them the same way as Task 1, loads the
trained model, and forecasts Global_active_power for the next hour(s).

Examples:
    python scripts/predict.py                                  # next hour, from the MySQL API
    python scripts/predict.py --source mongo                   # next hour, from the MongoDB API
    python scripts/predict.py --as-of 2010-11-20T17:00 --backtest-hours 24   # 24 one-hour forecasts vs real readings
    python scripts/predict.py --horizon 24                     # 24 hours ahead, if the model's features allow it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src.prediction.api_client import APIError, ReadingsClient  # noqa: E402
from src.prediction.pipeline import PipelineResult, run  # noqa: E402

HISTORY_HOURS_PLOTTED = 72
COLORS = {"history": "#2a78d6", "forecast": "#eb6834", "actual": "#1baf7a", "ink": "#52514e", "grid": "#e4e3df"}


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:5000"))
    parser.add_argument("--source", choices=["sql", "mongo"], default="sql", help="which database the API reads from")
    parser.add_argument("--model-dir", default=str(ROOT / "models"))
    parser.add_argument("--horizon", type=positive_int, default=1, help="hours to forecast")
    parser.add_argument("--as-of", type=datetime.fromisoformat, help="forecast from this past hour and compare with actuals")
    parser.add_argument("--backtest-hours", type=positive_int, default=0,
                        help="with --as-of: forecast each of the next N hours one step ahead and report the error")
    parser.add_argument("--lookback-hours", type=positive_int, help="history to fetch (default: what the model needs + 24h)")
    parser.add_argument("--output-dir", default=str(ROOT / "outputs" / "predictions"))
    parser.add_argument("--no-plot", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print(f"Forecasting from the {args.source.upper()} API at {args.api_url}")
    try:
        with ReadingsClient(args.api_url, args.source) as client:
            result = run(client, args.model_dir, args.horizon, args.as_of, args.lookback_hours, args.backtest_hours)
    except (APIError, FileNotFoundError, ImportError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    print_summary(result, walk_forward=args.backtest_hours > 0)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"forecast_{args.source}_{result.anchor:%Y%m%dT%H%M}_" + (
        f"bt{args.backtest_hours}" if args.backtest_hours else f"h{args.horizon}"
    )
    json_path = output_dir / f"{stem}.json"
    json_path.write_text(json.dumps(to_json(result, args), indent=2))
    print(f"\nSaved {json_path.relative_to(ROOT) if json_path.is_relative_to(ROOT) else json_path}")
    if not args.no_plot:
        plot_path = plot(result, output_dir / f"{stem}.png", walk_forward=args.backtest_hours > 0)
        print(f"Saved {plot_path.relative_to(ROOT) if plot_path.is_relative_to(ROOT) else plot_path}")
    return 0


def print_summary(result: PipelineResult, walk_forward: bool = False) -> None:
    bundle, report = result.bundle, result.report
    print(f"\n[1/4] Model     {bundle.model_type} model, {len(bundle.features)} features, target {bundle.target}")
    print(f"[2/4] Fetched   {report.raw_records} records up to {result.anchor} ({result.source})")
    print(
        f"[3/4] Cleaned   {report.hours} hourly rows, {report.imputed_hours} missing hours interpolated "
        f"(longest gap {report.longest_gap_hours}h)" + (", dropped incomplete last hour" if report.dropped_partial_hour else "")
    )
    if walk_forward:
        print(f"[4/4] Forecast  {len(result.predictions)} hours, each one hour ahead (walk-forward backtest)\n")
    else:
        print(f"[4/4] Forecast  {len(result.predictions)} hour(s) ahead\n")

    has_actuals = result.actuals is not None
    print(f"  {'hour':<19}  {'predicted kW':>12}" + (f"  {'actual kW':>10}  {'error':>7}" if has_actuals else ""))
    for ts, value in result.predictions.items():
        line = f"  {ts:%Y-%m-%d %H:%M}     {value:>12.3f}"
        if has_actuals:
            actual = result.actuals.get(ts)
            line += "  " + ("n/a".rjust(10) if pd.isna(actual) else f"{actual:>10.3f}  {value - actual:>+7.3f}")
        print(line)
    if result.mae is not None:
        print(f"\n  MAE over the window: {result.mae:.3f} kW")
    if result.skipped_hours:
        print(f"  Skipped {len(result.skipped_hours)} hour(s) whose inputs fall in a data gap.")


def to_json(result: PipelineResult, args: argparse.Namespace) -> dict:
    rows = []
    for ts, value in result.predictions.items():
        row = {"timestamp": ts.isoformat(), "predicted_kw": round(value, 4)}
        if result.actuals is not None and pd.notna(result.actuals.get(ts)):
            row["actual_kw"] = round(float(result.actuals[ts]), 4)
        rows.append(row)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api_url": args.api_url,
        "source": result.source,
        "mode": "walk-forward backtest" if args.backtest_hours else "backtest" if args.as_of else "forecast",
        "anchor_timestamp": result.anchor.isoformat(),
        "target": result.bundle.target,
        "model": {
            "type": result.bundle.model_type,
            "name": result.bundle.metadata.get("model_name"),
            "features": result.bundle.features,
        },
        "preprocessing": vars(result.report),
        "forecast": rows,
        "mae_kw": result.mae,
        "skipped_hours": [ts.isoformat() for ts in result.skipped_hours],
    }


def plot(result: PipelineResult, path: Path, walk_forward: bool = False) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target = result.bundle.target
    history = result.history[target].iloc[-HISTORY_HOURS_PLOTTED:]
    fig, ax = plt.subplots(figsize=(11, 4.5), dpi=120)
    ax.plot(history.index, history.values, color=COLORS["history"], linewidth=2, label="Observed (from API)")

    # Join the forecast line to the last observed hour so the two read as one continuous series.
    joined = [history.index[-1], *result.predictions.index], [history.iloc[-1], *result.predictions.values]
    ax.plot(*joined, color=COLORS["forecast"], linewidth=2, linestyle="--", label="Forecast")
    ax.scatter(result.predictions.index, result.predictions.values, color=COLORS["forecast"], s=36, zorder=3,
               edgecolors="white", linewidths=1.5)
    if result.actuals is not None and result.actuals.notna().any():
        ax.plot(result.actuals.index, result.actuals.values, color=COLORS["actual"], linewidth=2, marker="o",
                markersize=5, markeredgecolor="white", label="Actual")

    ax.axvline(result.anchor, color=COLORS["ink"], linewidth=1, linestyle=":")
    n = len(result.predictions)
    title = (f"{n} one-hour-ahead forecasts from {result.anchor:%Y-%m-%d %H:%M}" if walk_forward
             else f"Household power forecast, next {n}h from {result.anchor:%Y-%m-%d %H:%M}")
    if result.mae is not None:
        title += f" (MAE {result.mae:.3f} kW)"
    ax.set_title(title, loc="left", fontsize=12, color="#0b0b0b")
    ax.set_ylabel("Global active power (kW)", color=COLORS["ink"])
    ax.tick_params(colors=COLORS["ink"])
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLORS["grid"])
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="upper left", labelcolor=COLORS["ink"])
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


if __name__ == "__main__":
    sys.exit(main())
