"""Animated GIFs for the README, made from real simulations: a 16-QAM constellation as the SNR
rises, and the eye diagram as the roll-off grows."""
import io, pathlib, sys
import numpy as np
from PIL import Image
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from signallab import dsp, plots

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)


def frames_to_gif(frames, path, ms):
    ims = [Image.open(io.BytesIO(f)).convert("RGB") for f in frames]
    w = 640; ims = [im.resize((w, int(im.height * w / im.width)), Image.LANCZOS) for im in ims]
    pal = [im.quantize(colors=96, method=Image.Quantize.MEDIANCUT) for im in ims]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=ms, loop=0, optimize=True)


# 1. 16-QAM constellation, SNR 0 -> 30 dB
rng = np.random.default_rng(3)
tx = dsp.modulate(rng.integers(0, 2, 3000 * 4), "16QAM")
noise = (rng.standard_normal(tx.size) + 1j * rng.standard_normal(tx.size)) / np.sqrt(2)
pts = dsp.constellation("16QAM")
frames = []
snrs = list(np.arange(0, 31, 1.5)) + [30] * 4
for snr in snrs:
    rx = tx + noise * 10 ** (-snr / 20)
    ser = np.mean(np.abs(rx[:, None] - pts).argmin(1) != np.abs(tx[:, None] - pts).argmin(1))
    frames.append(plots.constellation_plot(rx, pts, f"16-QAM  SNR {snr:4.1f} dB  EVM {dsp.evm_percent(rx, tx):5.1f}%  SER {ser:.3f}"))
frames_to_gif(frames, OUT / "constellation_sweep.gif", 260)

# 2. Eye diagram, roll-off 0.1 -> 1.0
frames = []
betas = list(np.round(np.arange(0.1, 1.01, 0.1), 2)) + [1.0] * 3
for b in betas:
    _, mf, _ = dsp.shaped_signal("QPSK", float(b), 8, 600, 28, seed=5)
    frames.append(plots.eye_plot(mf, 8, 10, f"QPSK eye, roll-off β = {b:.1f}", traces=180))
frames_to_gif(frames, OUT / "eye_rolloff.gif", 350)
for f in OUT.glob("*.gif"):
    print(f.name, round(f.stat().st_size / 1e6, 2), "MB")
