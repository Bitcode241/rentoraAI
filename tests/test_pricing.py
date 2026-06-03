from datetime import datetime, timezone
from app.services import pricing


class FakeAsset:
    def __init__(self, h, hd, fd, dep):
        self.id = 1
        self.price_hour = h
        self.price_half_day = hd
        self.price_full_day = fd
        self.deposit = dep


def test_full_day_pricing():
    a = FakeAsset(80, 280, 480, 500)
    start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, 17, tzinfo=timezone.utc)  # 8 hours
    q = pricing.quote(a, start, end)
    assert q["total_price"] == 480
    assert q["deposit_amount"] == 500


def test_half_day_cheaper_than_hourly():
    a = FakeAsset(80, 280, 480, 500)
    start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
    end = datetime(2030, 1, 1, 13, tzinfo=timezone.utc)  # 4 hours
    q = pricing.quote(a, start, end)
    # min(half_day 280, 4*80=320) => 280
    assert q["total_price"] == 280


def test_multi_day():
    a = FakeAsset(80, 280, 480, 500)
    start = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
    end = datetime(2030, 1, 3, 9, tzinfo=timezone.utc)  # 48h = 2 full days
    q = pricing.quote(a, start, end)
    assert q["total_price"] == 960


class FakeAssetPct:
    def __init__(self, deposit_percent):
        self.id = 2
        self.deposit_percent = deposit_percent
        self.deposit = 0.0


class FakePackage:
    def __init__(self, pid, name, dur, price, guided=False):
        self.id = pid
        self.name = name
        self.duration_minutes = dur
        self.price = price
        self.guided = guided


def test_package_quote_with_percent_deposit():
    a = FakeAssetPct(deposit_percent=30)
    pkg = FakePackage(1, "8h", 480, 700.0)
    q = pricing.quote_package(a, pkg)
    assert q["total_price"] == 700.0
    assert q["deposit_amount"] == 210.0   # 30% of 700
    assert q["package_name"] == "8h"


def test_package_quote_sunset():
    a = FakeAssetPct(deposit_percent=30)
    pkg = FakePackage(2, "Sunset 2h", 120, 250.0)
    q = pricing.quote_package(a, pkg)
    assert q["total_price"] == 250.0
    assert q["deposit_amount"] == 75.0    # 30% of 250
