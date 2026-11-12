import numpy as np
import pytest
from signallab import dsp


@pytest.mark.parametrize("mod", dsp.MODULATIONS)
def test_unit_energy_and_round_trip(mod):
    c = dsp.constellation(mod)
    assert len(c) == 2 ** dsp.bits_per_symbol(mod)
    assert np.mean(np.abs(c) ** 2) == pytest.approx(1.0)
    b = np.random.default_rng(0).integers(0, 2, dsp.bits_per_symbol(mod) * 500)
    assert np.array_equal(dsp.demodulate(dsp.modulate(b, mod), mod), b)


@pytest.mark.parametrize("mod", ["QPSK", "16QAM", "64QAM"])
def test_gray_neighbours_differ_by_one_bit(mod):
    c = dsp.constellation(mod)
    for i in range(len(c)):
        d = np.abs(c - c[i]); d[i] = np.inf
        for j in np.where(np.isclose(d, d.min()))[0]:
            assert bin(i ^ j).count("1") == 1


@pytest.mark.parametrize("mod,ebn0", [("BPSK", 6), ("QPSK", 6), ("16QAM", 8), ("64QAM", 12)])
def test_awgn_simulation_matches_theory(mod, ebn0):
    sim, errs, _ = dsp.ber_sim(mod, ebn0, max_bits=4_000_000, min_errors=1500)
    assert sim == pytest.approx(float(dsp.ber_theory(mod, ebn0)), rel=0.12)


def test_rayleigh_closed_form_and_simulation():
    g = 10 ** (10 / 10)
    assert float(dsp.ber_theory("QPSK", 10, "rayleigh")) == pytest.approx(0.5 * (1 - np.sqrt(g / (1 + g))))
    sim, _, _ = dsp.ber_sim("QPSK", 10, "rayleigh", max_bits=2_000_000, min_errors=1500)
    assert sim == pytest.approx(float(dsp.ber_theory("QPSK", 10, "rayleigh")), rel=0.12)


def test_ofdm_ls_is_worse_than_perfect_and_cp_works():
    ls = dsp.ofdm_link(snr_db=15, n_symbols=300, estimator="ls")
    pf = dsp.ofdm_link(snr_db=15, n_symbols=300, estimator="perfect")
    assert pf["ber"] < ls["ber"] < 0.05
    assert dsp.ofdm_link(snr_db=80, n_symbols=50, estimator="perfect")["ber"] == 0  # no ISI with a long enough CP


def test_rrc_is_nyquist():
    g = dsp.rrc(0.35, 8, 10)
    rc = np.convolve(g, g)
    mid = rc.size // 2
    assert np.max(np.abs(rc[mid + 8::8][:6])) < 1e-2 * rc[mid]


def test_link_budgets():
    r = dsp.rf_link_budget(f_ghz=2.4, d_m=100)
    assert r["fspl_db"] == pytest.approx(80.05, abs=0.02)
    v = dsp.vlc_los_gain(semi_angle_deg=60, d_m=2.15)
    assert v["m"] == pytest.approx(1.0) and v["gain"] == pytest.approx(1.7546e-5, rel=1e-3)
