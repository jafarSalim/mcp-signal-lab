"""Digital communications building blocks: Gray-mapped constellations, channels, BER theory,
OFDM, pulse shaping and link budgets. Pure NumPy/SciPy, deterministic with a seed."""
from __future__ import annotations
import math
import numpy as np
from scipy.special import erfc

# ---------------------------------------------------------------- constellations
MODULATIONS = ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM", "256QAM"]


def bits_per_symbol(mod: str) -> int:
    return {"BPSK": 1, "QPSK": 2, "8PSK": 3, "16QAM": 4, "64QAM": 6, "256QAM": 8}[mod.upper()]


def _gray(n: int) -> np.ndarray:
    return np.arange(n) ^ (np.arange(n) >> 1)


def constellation(mod: str) -> np.ndarray:
    """Unit-average-energy points; index i carries the bit pattern of integer i (Gray mapping)."""
    mod = mod.upper()
    k = bits_per_symbol(mod)
    M = 2 ** k
    if mod == "BPSK":
        return np.array([1.0 + 0j, -1.0 + 0j])
    if mod in ("QPSK", "8PSK"):
        g = _gray(M)
        pts = np.empty(M, complex)
        pts[g] = np.exp(1j * (2 * np.pi * np.arange(M) / M + (np.pi / 4 if mod == "QPSK" else 0)))
        return pts
    side = int(math.isqrt(M))
    half = k // 2
    levels = np.arange(-(side - 1), side, 2, dtype=float)
    lv = np.empty(side)
    lv[_gray(side)] = levels                    # Gray code per axis
    idx = np.arange(M)
    pts = lv[idx >> half] + 1j * lv[idx & (side - 1)]
    return pts / np.sqrt(np.mean(np.abs(pts) ** 2))


def modulate(bits: np.ndarray, mod: str) -> np.ndarray:
    k = bits_per_symbol(mod)
    b = bits.reshape(-1, k)
    idx = b.dot(1 << np.arange(k - 1, -1, -1))
    return constellation(mod)[idx]


def demodulate(sym: np.ndarray, mod: str) -> np.ndarray:
    """Minimum-distance hard decisions back to bits."""
    pts = constellation(mod)
    k = bits_per_symbol(mod)
    out = np.empty(sym.size, dtype=int)
    for s in range(0, sym.size, 20000):           # chunked to bound memory
        d = np.abs(sym[s:s + 20000, None] - pts[None, :])
        out[s:s + 20000] = d.argmin(axis=1)
    return ((out[:, None] >> np.arange(k - 1, -1, -1)) & 1).reshape(-1)


# ---------------------------------------------------------------- channels
def awgn(x: np.ndarray, snr_db: float, rng: np.random.Generator, signal_power: float = 1.0) -> np.ndarray:
    n0 = signal_power / 10 ** (snr_db / 10)
    return x + np.sqrt(n0 / 2) * (rng.standard_normal(x.shape) + 1j * rng.standard_normal(x.shape))


def rayleigh(n: int, rng: np.random.Generator) -> np.ndarray:
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)


# ---------------------------------------------------------------- theory
def qfunc(x):
    return 0.5 * erfc(np.asarray(x) / np.sqrt(2))


def ber_theory(mod: str, ebn0_db, channel: str = "awgn"):
    """Bit error rate with Gray mapping. Exact for BPSK/QPSK; standard nearest-neighbour
    approximations for M-PSK and square M-QAM. Every expression has the form c * Q(sqrt(a * Eb/N0)),
    and over Rayleigh fading E[Q(sqrt(a g X))] with X ~ Exp(1) has the closed form
    0.5 * (1 - sqrt(a g / (2 + a g)))."""
    mod = mod.upper()
    g = 10 ** (np.asarray(ebn0_db, float) / 10)
    k = bits_per_symbol(mod)
    M = 2 ** k
    if mod in ("BPSK", "QPSK"):
        c, a = 1.0, 2.0
    elif mod == "8PSK":
        c, a = 2 / k, 2 * k * np.sin(np.pi / M) ** 2
    else:
        c, a = 4 / k * (1 - 1 / np.sqrt(M)), 3 * k / (M - 1)
    if channel == "awgn":
        return c * qfunc(np.sqrt(a * g))
    return c * 0.5 * (1 - np.sqrt(a * g / (2 + a * g)))


# ---------------------------------------------------------------- Monte Carlo
def ber_sim(mod: str, ebn0_db: float, channel: str = "awgn", max_bits: int = 2_000_000,
            min_errors: int = 200, seed: int = 1, block: int = 60_000) -> tuple[float, int, int]:
    """Simulated BER (errors / bits); stops after min_errors or max_bits. Rayleigh uses
    flat fading per symbol with perfect channel knowledge (zero-forcing equalizer)."""
    rng = np.random.default_rng(seed)
    k = bits_per_symbol(mod)
    esn0 = ebn0_db + 10 * np.log10(k)
    errs = nbits = 0
    blk = block - block % k
    while nbits < max_bits and errs < min_errors:
        b = rng.integers(0, 2, blk)
        s = modulate(b, mod)
        if channel == "rayleigh":
            h = rayleigh(s.size, rng)
            r = awgn(h * s, esn0, rng) / h
        else:
            r = awgn(s, esn0, rng)
        errs += int(np.sum(demodulate(r, mod) != b))
        nbits += blk
    return errs / nbits, errs, nbits


def evm_percent(rx: np.ndarray, tx: np.ndarray) -> float:
    return float(100 * np.sqrt(np.mean(np.abs(rx - tx) ** 2) / np.mean(np.abs(tx) ** 2)))


# ---------------------------------------------------------------- OFDM
def multipath_taps(n_taps: int, decay_db_per_tap: float, rng: np.random.Generator) -> np.ndarray:
    pdp = 10 ** (-decay_db_per_tap * np.arange(n_taps) / 10)
    pdp /= pdp.sum()
    return np.sqrt(pdp / 2) * (rng.standard_normal(n_taps) + 1j * rng.standard_normal(n_taps))


def ofdm_link(n_sc=64, cp=16, mod="QPSK", n_taps=6, decay_db=3.0, snr_db=15.0, n_symbols=400,
              pilot_spacing=4, estimator="ls", seed=1) -> dict:
    """OFDM over a static multipath channel. Comb pilots every `pilot_spacing` subcarriers,
    LS estimates at pilots, linear interpolation in frequency, one-tap equalizer.
    estimator = 'ls' or 'perfect'. Returns BER, MSE of the estimate, PAPR samples and the channel."""
    rng = np.random.default_rng(seed)
    k = bits_per_symbol(mod)
    pil = np.arange(0, n_sc, pilot_spacing)
    data = np.setdiff1d(np.arange(n_sc), pil)
    h = multipath_taps(n_taps, decay_db, rng)
    H = np.fft.fft(h, n_sc)
    errs = nbits = 0
    mse = []
    papr = []
    for _ in range(n_symbols):
        b = rng.integers(0, 2, data.size * k)
        X = np.zeros(n_sc, complex)
        X[data] = modulate(b, mod)
        X[pil] = 1 + 0j
        x = np.fft.ifft(X) * np.sqrt(n_sc)
        papr.append(10 * np.log10(np.max(np.abs(x) ** 2) / np.mean(np.abs(x) ** 2)))
        tx = np.concatenate([x[-cp:], x])
        rx = np.convolve(tx, h)[: tx.size]
        rx = awgn(rx, snr_db, rng, signal_power=np.mean(np.abs(rx) ** 2))
        Y = np.fft.fft(rx[cp:cp + n_sc]) / np.sqrt(n_sc)
        if estimator == "perfect":
            He = H
        else:
            hp = Y[pil] / X[pil]
            ext = np.append(pil, n_sc)                  # wrap the last pilot for interpolation
            hv = np.append(hp, hp[0])
            He = np.interp(np.arange(n_sc), ext, hv.real) + 1j * np.interp(np.arange(n_sc), ext, hv.imag)
        mse.append(np.mean(np.abs(He - H) ** 2) / np.mean(np.abs(H) ** 2))
        bh = demodulate(Y[data] / He[data], mod)
        errs += int(np.sum(bh != b)); nbits += b.size
    return dict(ber=errs / nbits, bits=nbits, nmse_db=float(10 * np.log10(max(np.mean(mse), 1e-30))),
                papr_db=np.array(papr), H=H, taps=h)


def papr_ccdf(papr_db: np.ndarray, grid=None):
    grid = np.arange(4, 13, 0.25) if grid is None else grid
    return grid, np.array([np.mean(papr_db > g) for g in grid])


# ---------------------------------------------------------------- pulse shaping
def rrc(beta: float, sps: int, span: int) -> np.ndarray:
    """Root-raised-cosine taps, unit energy."""
    t = np.arange(-span * sps / 2, span * sps / 2 + 1) / sps
    h = np.empty_like(t)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1 + beta * (4 / np.pi - 1)
        elif beta and abs(abs(4 * beta * ti) - 1) < 1e-9:
            h[i] = beta / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta)) + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))) / (np.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def shaped_signal(mod="QPSK", beta=0.35, sps=8, n_sym=4000, snr_db=None, seed=1):
    """Pulse-shaped baseband: returns (transmitted waveform, matched-filter output, symbols)."""
    rng = np.random.default_rng(seed)
    s = modulate(rng.integers(0, 2, n_sym * bits_per_symbol(mod)), mod)
    up = np.zeros(n_sym * sps, complex); up[::sps] = s
    g = rrc(beta, sps, 10)
    tx = np.convolve(up, g)
    rx = tx if snr_db is None else awgn(tx, snr_db - 10 * np.log10(sps), rng, signal_power=np.mean(np.abs(tx) ** 2) * sps)
    mf = np.convolve(rx, g)
    return tx, mf, s


def psd(x: np.ndarray, sps: int, nfft: int = 1024):
    """Welch power spectral density in dB vs frequency normalized to the symbol rate."""
    from scipy.signal import welch
    f, p = welch(x, fs=sps, nperseg=nfft, return_onesided=False)
    o = np.argsort(f)
    return f[o], 10 * np.log10(p[o] / p.max())


# ---------------------------------------------------------------- link budgets
def rf_link_budget(pt_dbm=20.0, gt_dbi=2.0, gr_dbi=2.0, f_ghz=2.4, d_m=100.0, bw_mhz=20.0, nf_db=7.0):
    fspl = 20 * np.log10(d_m) + 20 * np.log10(f_ghz * 1e9) - 147.55
    pr = pt_dbm + gt_dbi + gr_dbi - fspl
    noise = -174 + 10 * np.log10(bw_mhz * 1e6) + nf_db
    snr = pr - noise
    cap = bw_mhz * 1e6 * np.log2(1 + 10 ** (snr / 10))
    return dict(fspl_db=fspl, pr_dbm=pr, noise_dbm=noise, snr_db=snr, capacity_mbps=cap / 1e6)


def vlc_los_gain(semi_angle_deg=60.0, area_cm2=1.0, fov_deg=70.0, n_conc=1.5, d_m=2.15, phi_deg=0.0, psi_deg=0.0):
    """Lambertian line-of-sight DC gain (Kahn & Barry, 1997)."""
    m = -np.log(2) / np.log(np.cos(np.radians(semi_angle_deg)))
    if psi_deg > fov_deg:
        return dict(m=m, gain=0.0, gain_db=-np.inf)
    g = n_conc ** 2 / np.sin(np.radians(fov_deg)) ** 2
    H = (m + 1) * area_cm2 * 1e-4 / (2 * np.pi * d_m ** 2) * np.cos(np.radians(phi_deg)) ** m * g * np.cos(np.radians(psi_deg))
    return dict(m=m, gain=H, gain_db=10 * np.log10(H))
