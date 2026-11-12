"""Validates every simulator against closed-form theory and times every MCP tool through a real
MCP client session. Writes results/validation.json and the figures used in the README."""
import asyncio, base64, json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from mcp.client.client import Client
from signallab import dsp, plots
from signallab.server import mcp

OUT = pathlib.Path(__file__).resolve().parents[1] / "results"
OUT.mkdir(exist_ok=True)
GRID = {"BPSK": range(0, 11, 2), "QPSK": range(0, 11, 2), "8PSK": range(0, 15, 2), "16QAM": range(0, 15, 2),
        "64QAM": range(2, 19, 2), "256QAM": range(6, 25, 3)}

# 1. AWGN: every modulation, simulation vs theory
awgn = {}
for mod, grid in GRID.items():
    rows = []
    for e in grid:
        ber, errs, bits = dsp.ber_sim(mod, e, "awgn", max_bits=3_000_000, min_errors=300)
        rows.append(dict(ebn0=e, sim=ber, theory=float(dsp.ber_theory(mod, e)), errors=errs, bits=bits))
    awgn[mod] = rows
    print(mod, " ".join(f"{r['sim'] / r['theory']:.2f}" for r in rows if r["errors"] >= 300))

# 2. Rayleigh flat fading
ray = {}
for mod in ["BPSK", "QPSK", "16QAM"]:
    rows = []
    for e in range(0, 31, 5):
        ber, errs, bits = dsp.ber_sim(mod, e, "rayleigh", max_bits=3_000_000, min_errors=300)
        rows.append(dict(ebn0=e, sim=ber, theory=float(dsp.ber_theory(mod, e, "rayleigh")), errors=errs, bits=bits))
    ray[mod] = rows

# 3. OFDM: LS vs perfect channel knowledge over SNR
ofdm = []
for snr in range(0, 31, 3):
    ls = dsp.ofdm_link(snr_db=snr, n_symbols=600, estimator="ls")
    pf = dsp.ofdm_link(snr_db=snr, n_symbols=600, estimator="perfect")
    ofdm.append(dict(snr=snr, ber_ls=ls["ber"], ber_perfect=pf["ber"], nmse_ls_db=ls["nmse_db"], bits=ls["bits"]))
papr = dsp.ofdm_link(n_symbols=5000)["papr_db"]

# 4. Spectrum: occupied bandwidth vs roll-off
obw = []
for beta in [0.0, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0]:
    tx, _, _ = dsp.shaped_signal("QPSK", beta, 8, 8000)
    f, p = dsp.psd(tx, 8)
    lin = 10 ** (p / 10); c = np.cumsum(lin) / lin.sum()
    obw.append(dict(beta=beta, obw99=float(f[np.searchsorted(c, 0.995)] - f[np.searchsorted(c, 0.005)]), nyquist=1 + beta))

# 5. Every tool through the MCP protocol, timed
calls = [("ber_curve", {"modulation": "16QAM", "ebn0_stop_db": 12}), ("constellation", {"modulation": "64QAM", "snr_db": 25}),
         ("ofdm_link", {}), ("eye_diagram", {}), ("spectrum", {}), ("rf_link_budget", {}), ("vlc_los_gain", {})]
timing, transcript = [], []


async def run():
    async with Client(mcp) as c:
        tools = (await c.list_tools()).tools
        for name, args in calls:
            t0 = time.perf_counter()
            r = await c.call_tool(name, args)
            dt = time.perf_counter() - t0
            timing.append(dict(tool=name, seconds=dt, error=r.is_error))
            text = next(x.text for x in r.content if x.type == "text")
            transcript.append(dict(tool=name, arguments=args, result=json.loads(text)))
            for x in r.content:
                if x.type == "image":
                    (OUT / f"tool_{name}.png").write_bytes(base64.b64decode(x.data))
        return [dict(name=t.name, description=t.description.split("\n")[0], params=list(t.input_schema["properties"])) for t in tools]

tools = asyncio.run(run())

# Figures
curves = {}
for mod in GRID:
    e = [r["ebn0"] for r in awgn[mod]]
curves_fig, ax = plots.scope(9, 5.6)
for i, (mod, rows) in enumerate(awgn.items()):
    e = [r["ebn0"] for r in rows]; c = plots.TRACE[i % len(plots.TRACE)]
    ee = np.linspace(min(e), max(e), 100)
    ax.semilogy(ee, dsp.ber_theory(mod, ee), "-", color=c, lw=1.3, alpha=0.6)
    ax.semilogy(e, [r["sim"] if r["errors"] else np.nan for r in rows], "o", color=c, mfc="none", mew=1.8, ms=6, label=mod)
ax.set_ylim(1e-6, 0.5); ax.set_xlabel("Eb/N0 (dB)"); ax.set_ylabel("bit error rate")
ax.set_title("AWGN: simulation (circles) on top of theory (lines)"); plots.legend(ax)
(OUT / "ber_awgn_all.png").write_bytes(plots.png(curves_fig))

fig, ax = plots.scope(9, 5.6)
for i, (mod, rows) in enumerate(ray.items()):
    e = [r["ebn0"] for r in rows]; c = plots.TRACE[i + 1]
    ax.semilogy(e, [r["theory"] for r in rows], "-", color=c, lw=1.3, alpha=0.6)
    ax.semilogy(e, [r["sim"] for r in rows], "D", color=c, mfc="none", mew=1.6, ms=6, label=f"{mod} Rayleigh")
for mod, c in [("QPSK", plots.TRACE[0])]:
    ee = np.linspace(0, 30, 100); ax.semilogy(ee, np.maximum(dsp.ber_theory(mod, ee), 1e-9), ":", color="#6fbf98", lw=1.2, label="QPSK AWGN (reference)")
ax.set_ylim(1e-6, 0.5); ax.set_xlabel("Eb/N0 (dB)"); ax.set_ylabel("bit error rate"); ax.set_title("Rayleigh fading costs ~10 dB per decade of BER"); plots.legend(ax)
(OUT / "ber_rayleigh.png").write_bytes(plots.png(fig))

fig, ax = plots.scope(9, 5.2)
s = [r["snr"] for r in ofdm]
ax.semilogy(s, [r["ber_perfect"] or np.nan for r in ofdm], "-o", color=plots.TRACE[1], label="perfect channel knowledge")
ax.semilogy(s, [r["ber_ls"] or np.nan for r in ofdm], "-s", color=plots.TRACE[2], label="LS pilots + interpolation")
ax.set_xlabel("SNR (dB)"); ax.set_ylabel("bit error rate"); ax.set_title("OFDM, 64 subcarriers, 6-tap channel, QPSK"); plots.legend(ax)
(OUT / "ofdm_ls_vs_perfect.png").write_bytes(plots.png(fig))

fig, ax = plots.scope(8, 4.8)
b = [r["beta"] for r in obw]
ax.plot(b, [r["nyquist"] for r in obw], "--", color=plots.TRACE[3], label="Nyquist bandwidth (1 + β)")
ax.plot(b, [r["obw99"] for r in obw], "-o", color=plots.TRACE[1], label="measured 99% bandwidth")
ax.set_xlabel("roll-off β"); ax.set_ylabel("bandwidth / symbol rate"); ax.set_title("Root-raised-cosine: bandwidth vs roll-off"); plots.legend(ax)
(OUT / "bandwidth_vs_rolloff.png").write_bytes(plots.png(fig))

fig, ax = plots.scope(8, 4.2)
names = [t["tool"] for t in timing]
ax.barh(names, [t["seconds"] * 1000 for t in timing], color=[plots.TRACE[i % 6] for i in range(len(names))])
for i, t in enumerate(timing):
    ax.text(t["seconds"] * 1000, i, f"  {t['seconds'] * 1000:.0f} ms", va="center", color=plots.TEXT, fontsize=9)
ax.set_xlabel("round trip through the MCP protocol (ms)"); ax.set_title("Every tool, called by a real MCP client"); ax.invert_yaxis()
(OUT / "tool_timing.png").write_bytes(plots.png(fig))

acc = {mod: max(abs(np.log10(r["sim"] / r["theory"])) for r in rows if r["errors"] >= 300) for mod, rows in awgn.items()}
json.dump(dict(awgn=awgn, rayleigh=ray, ofdm=ofdm, papr_mean=float(papr.mean()), papr_99=float(np.percentile(papr, 99)),
               obw=obw, timing=timing, tools=tools, transcript=transcript,
               max_log10_error={k: float(v) for k, v in acc.items()}),
          open(OUT / "validation.json", "w"), indent=1)
print("max deviation (dB of BER ratio):", {k: round(10 * v, 2) for k, v in acc.items()})
print("timing ms:", {t["tool"]: round(t["seconds"] * 1000) for t in timing})
print("ofdm", [(r["snr"], r["ber_ls"], r["ber_perfect"]) for r in ofdm])
print("rayleigh", {m: [(r["ebn0"], f"{r['sim']:.2e}", f"{r['theory']:.2e}") for r in rows] for m, rows in ray.items()})
print("obw", obw, "papr", papr.mean(), np.percentile(papr, 99))
