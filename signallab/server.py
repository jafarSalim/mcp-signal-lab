"""The MCP server: each tool runs a real simulation and returns numbers plus an oscilloscope-style plot."""
from __future__ import annotations
import json
import numpy as np
from mcp.server.mcpserver import MCPServer, Image
from mcp.server.mcpserver.exceptions import ToolError
from . import dsp, plots

mcp = MCPServer(
    "signal-lab",
    instructions="A digital communications lab. Tools simulate modulation, channels, OFDM, pulse shaping and "
                 "link budgets and return measured numbers with a plot. Results are Monte Carlo simulations, "
                 "so mention the number of simulated bits when you quote a BER.",
)


def _snr_list(start: float, stop: float, step: float) -> list[float]:
    n = int(round((stop - start) / step)) + 1
    if not 1 <= n <= 40:
        raise ToolError("use between 1 and 40 SNR points")
    return [round(start + i * step, 3) for i in range(n)]


@mcp.tool()
def ber_curve(modulation: str = "QPSK", ebn0_start_db: float = 0, ebn0_stop_db: float = 12, step_db: float = 2,
              channel: str = "awgn", max_bits: int = 1_000_000) -> list:
    """Simulate bit error rate vs Eb/N0 and compare with theory.

    modulation: BPSK, QPSK, 8PSK, 16QAM, 64QAM or 256QAM. channel: 'awgn' or 'rayleigh' (flat fading,
    perfect channel knowledge). max_bits caps the simulation per point (stops early after 200 errors)."""
    mod = modulation.upper()
    if mod not in dsp.MODULATIONS:
        raise ToolError(f"modulation must be one of {dsp.MODULATIONS}")
    if channel not in ("awgn", "rayleigh"):
        raise ToolError("channel must be 'awgn' or 'rayleigh'")
    max_bits = int(min(max(max_bits, 10_000), 5_000_000))
    snrs = _snr_list(ebn0_start_db, ebn0_stop_db, step_db)
    rows = []
    for e in snrs:
        ber, errs, bits = dsp.ber_sim(mod, e, channel, max_bits=max_bits)
        rows.append(dict(ebn0_db=e, ber_sim=ber, ber_theory=float(dsp.ber_theory(mod, e, channel)), errors=errs, bits=bits))
    img = plots.ber_plot(snrs, {f"{mod} simulated": ([r["ber_sim"] for r in rows], "sim"),
                                f"{mod} theory": ([r["ber_theory"] for r in rows], "theory")},
                         f"{mod} over {channel.upper()}")
    return [json.dumps({"modulation": mod, "channel": channel, "points": rows}, indent=1), Image(data=img, format="png")]


@mcp.tool()
def constellation(modulation: str = "16QAM", snr_db: float = 20, phase_noise_deg: float = 0, n_symbols: int = 4000) -> list:
    """Received constellation after AWGN (and optional phase noise, RMS degrees). Returns EVM and symbol error rate."""
    mod = modulation.upper()
    rng = np.random.default_rng(7)
    n_symbols = int(min(max(n_symbols, 200), 50_000))
    tx = dsp.modulate(rng.integers(0, 2, n_symbols * dsp.bits_per_symbol(mod)), mod)
    rx = dsp.awgn(tx * np.exp(1j * np.radians(phase_noise_deg) * rng.standard_normal(tx.size)), snr_db, rng)
    pts = dsp.constellation(mod)
    ser = float(np.mean(np.abs(rx[:, None] - pts).argmin(1) != np.abs(tx[:, None] - pts).argmin(1)))
    evm = dsp.evm_percent(rx, tx)
    img = plots.constellation_plot(rx, pts, f"{mod}  SNR {snr_db:g} dB  EVM {evm:.1f}%")
    return [json.dumps(dict(modulation=mod, snr_db=snr_db, phase_noise_deg=phase_noise_deg, evm_percent=evm, symbol_error_rate=ser, symbols=n_symbols)),
            Image(data=img, format="png")]


@mcp.tool()
def ofdm_link(subcarriers: int = 64, cyclic_prefix: int = 16, modulation: str = "QPSK", channel_taps: int = 6,
              snr_db: float = 15, pilot_spacing: int = 4, estimator: str = "ls", n_symbols: int = 300) -> list:
    """OFDM over a multipath channel with comb pilots. estimator: 'ls' (pilots + interpolation) or 'perfect'.
    Returns BER, channel-estimate NMSE, PAPR statistics, and a plot of |H| and the PAPR CCDF."""
    if channel_taps > cyclic_prefix + 1:
        raise ToolError("channel_taps must not exceed cyclic_prefix + 1, or symbols will interfere")
    r = dsp.ofdm_link(subcarriers, cyclic_prefix, modulation.upper(), channel_taps, 3.0, snr_db, int(min(n_symbols, 3000)),
                      pilot_spacing, estimator)
    g, cc = dsp.papr_ccdf(r["papr_db"])
    img = plots.ofdm_plot(r["H"], g, cc, f"OFDM {subcarriers} subcarriers, {modulation.upper()}, SNR {snr_db:g} dB, {estimator.upper()}")
    out = dict(ber=r["ber"], bits=r["bits"], channel_nmse_db=r["nmse_db"], papr_mean_db=float(np.mean(r["papr_db"])),
               papr_99_db=float(np.percentile(r["papr_db"], 99)), data_subcarriers=subcarriers - len(range(0, subcarriers, pilot_spacing)))
    return [json.dumps(out), Image(data=img, format="png")]


@mcp.tool()
def eye_diagram(modulation: str = "QPSK", rolloff: float = 0.35, snr_db: float = 30, samples_per_symbol: int = 8) -> list:
    """Eye diagram after root-raised-cosine shaping and matched filtering."""
    sps = int(min(max(samples_per_symbol, 4), 32))
    _, mf, s = dsp.shaped_signal(modulation.upper(), rolloff, sps, 3000, snr_db)
    img = plots.eye_plot(mf, sps, 10, f"eye  {modulation.upper()}  roll-off {rolloff:g}  SNR {snr_db:g} dB")
    d = 10 * sps
    samples = mf[d: d + s.size * sps: sps][: s.size]
    opening = float(np.min(np.abs(samples.real)) / np.mean(np.abs(samples.real)))
    return [json.dumps(dict(rolloff=rolloff, snr_db=snr_db, eye_opening_ratio=opening)), Image(data=img, format="png")]


@mcp.tool()
def spectrum(modulation: str = "QPSK", rolloff: float = 0.35, samples_per_symbol: int = 8) -> list:
    """Power spectral density of a root-raised-cosine shaped signal. Returns the 99% occupied bandwidth."""
    sps = int(min(max(samples_per_symbol, 4), 32))
    tx, _, _ = dsp.shaped_signal(modulation.upper(), rolloff, sps, 8000)
    f, p = dsp.psd(tx, sps)
    lin = 10 ** (p / 10); c = np.cumsum(lin) / lin.sum()
    obw = float(f[np.searchsorted(c, 0.995)] - f[np.searchsorted(c, 0.005)])
    img = plots.spectrum_plot(f, p, f"PSD  {modulation.upper()}  roll-off {rolloff:g}")
    return [json.dumps(dict(rolloff=rolloff, occupied_bw_99_over_symbol_rate=obw, theory=1 + rolloff)), Image(data=img, format="png")]


@mcp.tool()
def rf_link_budget(tx_power_dbm: float = 20, tx_gain_dbi: float = 2, rx_gain_dbi: float = 2, frequency_ghz: float = 2.4,
                   distance_m: float = 100, bandwidth_mhz: float = 20, noise_figure_db: float = 7) -> str:
    """Free-space link budget: path loss, received power, noise floor, SNR and Shannon capacity."""
    r = dsp.rf_link_budget(tx_power_dbm, tx_gain_dbi, rx_gain_dbi, frequency_ghz, distance_m, bandwidth_mhz, noise_figure_db)
    return json.dumps({k: round(float(v), 3) for k, v in r.items()})


@mcp.tool()
def vlc_los_gain(semi_angle_deg: float = 60, detector_area_cm2: float = 1, fov_deg: float = 70,
                 concentrator_index: float = 1.5, distance_m: float = 2.15, irradiance_deg: float = 0, incidence_deg: float = 0) -> str:
    """Line-of-sight DC gain of a visible light link (Lambertian LED, photodiode with concentrator)."""
    r = dsp.vlc_los_gain(semi_angle_deg, detector_area_cm2, fov_deg, concentrator_index, distance_m, irradiance_deg, incidence_deg)
    return json.dumps({k: float(v) for k, v in r.items()})


def main():
    mcp.run()
