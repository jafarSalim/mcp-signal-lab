import asyncio, json
from mcp.client.client import Client
from signallab.server import mcp


def call(name, args=None):
    async def go():
        async with Client(mcp) as c:
            return await c.call_tool(name, args or {})
    return asyncio.run(go())


def test_lists_seven_tools():
    async def go():
        async with Client(mcp) as c:
            return {t.name for t in (await c.list_tools()).tools}
    assert asyncio.run(go()) == {"ber_curve", "constellation", "ofdm_link", "eye_diagram", "spectrum", "rf_link_budget", "vlc_los_gain"}


def test_ber_curve_returns_numbers_and_a_png():
    r = call("ber_curve", {"modulation": "QPSK", "ebn0_start_db": 0, "ebn0_stop_db": 4, "step_db": 2})
    assert not r.is_error
    data = json.loads(r.content[0].text)
    assert len(data["points"]) == 3 and r.content[1].type == "image" and r.content[1].mime_type == "image/png"


def test_bad_input_gives_a_readable_error():
    r = call("ofdm_link", {"channel_taps": 40, "cyclic_prefix": 16})
    assert r.is_error and "cyclic_prefix" in r.content[0].text
