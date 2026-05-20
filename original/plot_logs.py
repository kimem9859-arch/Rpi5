"""
Test log visualizer.

CLI:
    python plot_logs.py                  # latest session
    python plot_logs.py 20260513_190244  # specific session

Import (for view_stream_test.py auto-call):
    from plot_logs import generate_plots
    generate_plots(log_dir)
"""
import os
import sys
import glob
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_ROOT = os.path.join(BASE_DIR, "logs")


# =============================================================================
# Helpers
# =============================================================================
def find_latest_session():
    sessions = [d for d in glob.glob(os.path.join(LOGS_ROOT, "*")) if os.path.isdir(d)]
    if not sessions:
        return None
    return max(sessions, key=os.path.getmtime)


def resolve_log_dir(arg):
    if arg is None:
        d = find_latest_session()
        if d is None:
            raise FileNotFoundError(f"세션 폴더 없음: {LOGS_ROOT}")
        return d
    if os.path.isabs(arg) and os.path.isdir(arg):
        return arg
    candidate = os.path.join(LOGS_ROOT, arg)
    if os.path.isdir(candidate):
        return candidate
    raise FileNotFoundError(f"세션을 찾을 수 없음: {arg}")


def to_elapsed(df):
    if df.empty:
        df["elapsed"] = []
        return df
    ts = pd.to_datetime(df["date"] + " " + df["time"])
    df["elapsed"] = (ts - ts.iloc[0]).dt.total_seconds()
    return df


def load_csvs(log_dir):
    def _read(name):
        p = os.path.join(log_dir, name)
        if not os.path.exists(p):
            return pd.DataFrame()
        return pd.read_csv(p)

    inf = to_elapsed(_read("inference_log.csv"))
    obj = to_elapsed(_read("object_log.csv"))
    trk = to_elapsed(_read("tracking_log.csv"))
    cap = to_elapsed(_read("capture_log.csv"))
    net = to_elapsed(_read("network_log.csv"))
    mode = "usb" if not cap.empty else "esp32"
    return inf, obj, trk, cap, net, mode


# =============================================================================
# Plots
# =============================================================================
def plot_confidence(ax, inf):
    if inf.empty:
        ax.set_title("[1] Confidence (no data)")
        return
    ax.plot(inf["elapsed"], inf["avg_conf"], color="steelblue", label="avg")
    ax.fill_between(inf["elapsed"], inf["min_conf"], inf["max_conf"],
                    color="steelblue", alpha=0.2, label="min~max")
    ax.axhline(0.65, color="green", linestyle="--", linewidth=0.8, label="CONF_HIGH")
    ax.axhline(0.50, color="orange", linestyle="--", linewidth=0.8, label="CONF_LOW")
    ax.set_title("[1] YOLO Confidence")
    ax.set_xlabel("elapsed (s)")
    ax.set_ylabel("conf")
    ax.set_ylim(0, 1)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(alpha=0.3)


def plot_infer_fps(ax, inf):
    if inf.empty:
        ax.set_title("[2] Inference time (no data)")
        return
    ax.plot(inf["elapsed"], inf["avg_infer_ms"], color="crimson", label="infer ms")
    ax.set_xlabel("elapsed (s)")
    ax.set_ylabel("infer ms", color="crimson")
    ax.tick_params(axis="y", labelcolor="crimson")
    ax.grid(alpha=0.3)

    ax2 = ax.twinx()
    ax2.plot(inf["elapsed"], inf["frame_count"], color="navy",
             linestyle="--", label="processed fps")
    ax2.set_ylabel("processed fps", color="navy")
    ax2.tick_params(axis="y", labelcolor="navy")
    ax.set_title("[2] Inference time vs Processed FPS")


def plot_input(ax, mode, cap, net):
    if mode == "usb":
        if cap.empty:
            ax.set_title("[3] USB capture (no data)")
            return
        ax.plot(cap["elapsed"], cap["capture_fps"], color="seagreen", label="capture fps")
        ax.set_xlabel("elapsed (s)")
        ax.set_ylabel("capture fps")
        ax.set_title("[3] USB Capture FPS")
        ax.grid(alpha=0.3)
        if cap["capture_fail_total"].max() > 0:
            ax2 = ax.twinx()
            ax2.plot(cap["elapsed"], cap["capture_fail_total"],
                     color="red", linestyle=":", label="fail total")
            ax2.set_ylabel("capture fail (cum)", color="red")
    else:
        if net.empty:
            ax.set_title("[3] Network (no data)")
            return
        ax.bar(net["elapsed"], net["rx_bytes_1s"] / 1024.0,
               width=0.8, color="lightsteelblue", label="rx KB/s")
        ax.set_xlabel("elapsed (s)")
        ax.set_ylabel("rx KB/s", color="steelblue")
        ax.tick_params(axis="y", labelcolor="steelblue")
        ax2 = ax.twinx()
        ax2.plot(net["elapsed"], net["recv_fps"], color="darkred",
                 marker="o", markersize=3, label="recv fps")
        ax2.set_ylabel("recv fps", color="darkred")
        ax2.tick_params(axis="y", labelcolor="darkred")
        for _, row in net.iterrows():
            if row["recv_fps"] == 0:
                ax.axvspan(row["elapsed"], row["elapsed"] + 1,
                           color="red", alpha=0.12)
        ax.set_title("[3] ESP32 Network (red shade = 0 fps)")
        ax.grid(alpha=0.3)


def plot_tracks_gantt(ax, trk):
    if trk.empty:
        ax.set_title("[4] Track Gantt (no data)")
        return
    ids = sorted(trk["track_id"].unique())
    cmap = cm.get_cmap("tab20", max(len(ids), 1))
    for idx, tid in enumerate(ids):
        g = trk[trk["track_id"] == tid].sort_values("elapsed")
        start = g["elapsed"].min()
        end = g["elapsed"].max() + 1.0
        ax.broken_barh([(start, end - start)], (idx - 0.4, 0.8),
                       facecolors=cmap(idx % cmap.N))
    ax.set_yticks(range(len(ids)))
    ax.set_yticklabels([f"#{tid}" for tid in ids], fontsize=8)
    ax.set_xlabel("elapsed (s)")
    ax.set_title(f"[4] Track Gantt — {len(ids)} tracks")
    ax.grid(alpha=0.3, axis="x")


def plot_trajectory(ax, obj):
    if obj.empty:
        ax.set_title("[5] Object Trajectory (no data)")
        return
    ids = sorted(obj["track_id"].unique())
    cmap = cm.get_cmap("tab20", max(len(ids), 1))
    for idx, tid in enumerate(ids):
        g = obj[obj["track_id"] == tid].sort_values("elapsed")
        ax.plot(g["avg_center_x"], g["avg_center_y"],
                color=cmap(idx % cmap.N), marker="o", markersize=3,
                linewidth=1.0, label=f"#{tid}")
    ax.set_xlabel("center_x (px)")
    ax.set_ylabel("center_y (px)")
    ax.set_title("[5] Object Trajectory")
    ax.invert_yaxis()
    ax.grid(alpha=0.3)
    if len(ids) <= 10:
        ax.legend(fontsize=7, loc="best")


def plot_detection_rate(ax, inf):
    if inf.empty:
        ax.set_title("[6] Detection rate (no data)")
        return
    ax.fill_between(inf["elapsed"], 0, inf["detection_rate"],
                    color="mediumseagreen", alpha=0.5, step="mid")
    ax.plot(inf["elapsed"], inf["detection_rate"], color="darkgreen", linewidth=0.8)
    ax.set_xlabel("elapsed (s)")
    ax.set_ylabel("detection rate")
    ax.set_ylim(0, 1.05)
    ax.set_title("[6] Detection Rate (frames with person / frames)")
    ax.grid(alpha=0.3)


# =============================================================================
# Public entry point
# =============================================================================
def generate_plots(log_dir, show=False):
    """Generate summary.png inside log_dir. Returns output path or None."""
    inf, obj, trk, cap, net, mode = load_csvs(log_dir)

    fig, axes = plt.subplots(3, 2, figsize=(16, 12))
    fig.suptitle(f"Session: {os.path.basename(log_dir)}  (mode={mode.upper()})",
                 fontsize=14, fontweight="bold")

    plot_confidence(axes[0, 0], inf)
    plot_infer_fps(axes[0, 1], inf)
    plot_input(axes[1, 0], mode, cap, net)
    plot_tracks_gantt(axes[1, 1], trk)
    plot_trajectory(axes[2, 0], obj)
    plot_detection_rate(axes[2, 1], inf)

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    out_path = os.path.join(log_dir, "summary.png")
    fig.savefig(out_path, dpi=120)
    print(f"[그래프 저장] {out_path}")

    # Console summary
    if not inf.empty:
        duration = inf["elapsed"].max() + 1
        total_frames = int(inf["frame_count"].sum())
        confs = inf.loc[inf["avg_conf"] > 0, "avg_conf"]
        avg_conf = confs.mean() if not confs.empty else 0.0
        avg_infer = inf.loc[inf["avg_infer_ms"] > 0, "avg_infer_ms"].mean()
        n_tracks = trk["track_id"].nunique() if not trk.empty else 0
        max_dur = trk.groupby("track_id")["duration_sec"].max().max() if not trk.empty else 0
        print("-" * 50)
        print(f"세션 시간       : {duration:.1f}초")
        print(f"총 처리 프레임   : {total_frames}")
        print(f"평균 신뢰도      : {avg_conf:.3f}")
        print(f"평균 추론시간    : {avg_infer:.1f} ms")
        print(f"발급 track 수    : {n_tracks}")
        print(f"최장 트랙 유지   : {max_dur:.1f}초")
        print("-" * 50)

    if show:
        plt.show()
    plt.close(fig)
    return out_path


# =============================================================================
# CLI
# =============================================================================
if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    log_dir = resolve_log_dir(arg)
    print(f"[대상 세션] {log_dir}")
    generate_plots(log_dir, show=False)
