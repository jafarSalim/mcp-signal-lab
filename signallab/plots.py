"""Oscilloscope-style figures: black screen, phosphor traces, graticule grid."""
from __future__ import annotations
import io
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCREEN, GRID, TEXT = "#04100b", "#0f3b29", "#9cf5c7"
TRACE = ["#39ff14", "#00e5ff", "#ffb000", "#ff2bd6", "#ffffff", "#7c4dff"]


def scope(w=8.0, h=5.0, polar=False):
    plt.rcParams.update({"font.family": "DejaVu Sans Mono", "font.size": 10})
    fig = plt.figure(figsize=(w, h), dpi=150, facecolor="#020604")
    ax = fig.add_subplot(111, facecolor=SCREEN)
    for s in ax.spines.values():
        s.set_color("#1f6b4a"); s.set_linewidth(1.4)
    ax.tick_params(colors=TEXT, which="both")
    ax.grid(True, color=GRID, linewidth=0.8, which="major")
    ax.grid(True, color=GRID, linewidth=0.4, which="minor", alpha=0.6)
    ax.minorticks_on()
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(TEXT); ax.yaxis.label.set_color(TEXT); ax.title.set_color("#d7ffe9")
    return fig, ax


def legend(ax):
    lg = ax.legend(facecolor="#06170f", edgecolor="#1f6b4a", labelcolor=TEXT, fontsize=9)
    return lg


def png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def ber_plot(ebn0, curves: dict, title: str) -> bytes:
    """curves: {label: (values, style)} with style 'sim' (markers) or 'theory' (line)."""
    fig, ax = scope()
    for i, (lab, (vals, style)) in enumerate(curves.items()):
        c = TRACE[(i // 2) % len(TRACE)]
        v = np.where(np.asarray(vals) > 0, vals, np.nan)
        if style == "theory":
            ax.semilogy(ebn0, v, "-", color=c, lw=1.6, alpha=0.75, label=lab)
        else:
            ax.semilogy(ebn0, v, "o", color=c, ms=6, mfc="none", mew=1.8, label=lab)
    ax.set_xlabel("Eb/N0 (dB)"); ax.set_ylabel("bit error rate"); ax.set_title(title)
    ax.set_ylim(bottom=1e-6); legend(ax)
    return png(fig)


def constellation_plot(rx, ideal, title) -> bytes:
    fig, ax = scope(5.6, 5.6)
    ax.plot(rx.real, rx.imag, ".", color=TRACE[0], ms=1.6, alpha=0.45)
    ax.plot(ideal.real, ideal.imag, "+", color=TRACE[3], ms=10, mew=2)
    lim = 1.6 * np.max(np.abs(ideal))
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
    ax.set_xlabel("in-phase"); ax.set_ylabel("quadrature"); ax.set_title(title)
    return png(fig)


def eye_plot(mf, sps, span, title, traces=200) -> bytes:
    fig, ax = scope()
    d = span * sps                       # delay of the two RRC filters
    t = np.arange(2 * sps + 1) / sps - 1
    for k in range(traces):
        st = d + k * sps
        seg = mf[st - sps: st + sps + 1].real
        if seg.size == t.size:
            ax.plot(t, seg, color=TRACE[0], lw=0.6, alpha=0.25)
    ax.set_xlabel("time (symbols)"); ax.set_ylabel("amplitude, I branch"); ax.set_title(title)
    return png(fig)


def spectrum_plot(f, p, title) -> bytes:
    fig, ax = scope()
    ax.plot(f, p, color=TRACE[1], lw=1.4)
    ax.fill_between(f, p, -80, color=TRACE[1], alpha=0.12)
    ax.set_ylim(-70, 3); ax.set_xlabel("frequency / symbol rate"); ax.set_ylabel("PSD (dB)"); ax.set_title(title)
    return png(fig)


def ofdm_plot(H, papr_grid, ccdf, title) -> bytes:
    plt.rcParams.update({"font.family": "DejaVu Sans Mono", "font.size": 10})
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150, facecolor="#020604")
    for ax in axs:
        ax.set_facecolor(SCREEN); ax.grid(True, color=GRID); ax.tick_params(colors=TEXT)
        for s in ax.spines.values():
            s.set_color("#1f6b4a")
        ax.xaxis.label.set_color(TEXT); ax.yaxis.label.set_color(TEXT); ax.title.set_color("#d7ffe9")
    axs[0].plot(20 * np.log10(np.abs(H)), color=TRACE[2], lw=1.6, marker=".", ms=4)
    axs[0].set_xlabel("subcarrier"); axs[0].set_ylabel("|H| (dB)"); axs[0].set_title("channel frequency response")
    axs[1].semilogy(papr_grid, np.where(ccdf > 0, ccdf, np.nan), color=TRACE[3], lw=1.8)
    axs[1].set_xlabel("PAPR threshold (dB)"); axs[1].set_ylabel("P(PAPR > x)"); axs[1].set_title("PAPR CCDF")
    fig.suptitle(title, color="#d7ffe9")
    return png(fig)
