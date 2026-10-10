"""sensors.py — temperature probing against a fixture sysfs tree."""
from __future__ import annotations

from island import sensors


def _zone(tmp_path, name, kind, milli_c):
    z = tmp_path / name
    z.mkdir(parents=True)
    (z / "type").write_text(kind)
    (z / "temp").write_text(str(milli_c))
    return z


def test_sysfs_reads_the_preferred_zone(tmp_path, monkeypatch):
    _zone(tmp_path, "thermal_zone0", "acpitz", 42000)
    _zone(tmp_path, "thermal_zone1", "x86_pkg_temp", 55000)
    monkeypatch.setattr(sensors, "_SYSFS_THERMAL",
                        str(tmp_path))
    got = sensors._from_sysfs()
    assert got is not None
    assert 40.0 < got < 70.0


def test_sysfs_returns_none_when_there_is_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(sensors, "_SYSFS_THERMAL", str(tmp_path))
    assert sensors._from_sysfs() is None


def test_sysfs_rejects_implausible_readings(tmp_path, monkeypatch):
    _zone(tmp_path, "thermal_zone0", "acpitz", 999999)   # 999C
    monkeypatch.setattr(sensors, "_SYSFS_THERMAL", str(tmp_path))
    assert sensors._from_sysfs() is None


def test_zero_reading_is_not_discarded(monkeypatch):
    """`return _from_psutil() or _from_sysfs()` threw away a legitimate 0.0
    reading and read a different sensor instead."""
    monkeypatch.setattr(sensors, "_from_psutil", lambda: 0.0)
    monkeypatch.setattr(sensors, "_from_sysfs", lambda: 99.0)
    assert sensors.get_cpu_temp(fresh=True) == 0.0


def test_a_real_reading_wins_over_the_fallback(monkeypatch):
    monkeypatch.setattr(sensors, "_from_psutil", lambda: 51.5)
    monkeypatch.setattr(sensors, "_from_sysfs", lambda: 10.0)
    assert sensors.get_cpu_temp(fresh=True) == 51.5


def test_falls_through_when_psutil_has_nothing(monkeypatch):
    monkeypatch.setattr(sensors, "_from_psutil", lambda: None)
    monkeypatch.setattr(sensors, "_from_sysfs", lambda: 44.0)
    assert sensors.get_cpu_temp(fresh=True) == 44.0


def test_repeat_reads_are_served_from_the_cache(monkeypatch):
    """Three callers polled at three different cadences and each re-read
    every thermal zone from scratch."""
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return 50.0

    monkeypatch.setattr(sensors, "_from_psutil", counting)
    for _ in range(5):
        sensors.get_cpu_temp(fresh=True) if calls["n"] == 0 else sensors.get_cpu_temp()
    assert calls["n"] == 1


def test_format_temp():
    assert sensors.format_temp(None) == "—"
    assert sensors.format_temp(47.4, short=True) == "47°"
    assert sensors.format_temp(47.4) == "47.4°C"


def test_sensors_reads_each_zone_file_once_per_sample(tmp_path, monkeypatch):
    """The zone type used to be read twice per zone: once in the sort key
    and once again in the loop body."""
    from pathlib import Path as _P
    for i in range(4):
        _zone(tmp_path, f"thermal_zone{i}", f"type{i}", 40000 + i)
    monkeypatch.setattr(sensors, "_SYSFS_THERMAL", str(tmp_path))
    reads = {"n": 0}
    orig = _P.read_text

    def counting(self, *a, **k):
        if self.name == "type":
            reads["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(_P, "read_text", counting)
    sensors._from_sysfs()
    assert reads["n"] == 4, (
        f"expected one read per zone, saw {reads['n']}")
