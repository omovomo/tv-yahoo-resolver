from pathlib import Path

from tv_market_identity.config import load_screen_config


def test_market_only_identity_coverage_config(tmp_path: Path):
    cfg_path = tmp_path / "coverage.ini"
    cfg_path.write_text(
        """[General]
PresetName = Coverage
AssetType = STOCKS
MinScore = 0

[TradingView]
StockFilterSchema = 2
Limit = 1000
OrderBy = market_cap_basic
Ascending = false

[Filters]
market = market=switzerland
""",
        encoding="utf-8",
    )
    cfg = load_screen_config(cfg_path)
    assert cfg.market == "switzerland"
    assert cfg.min_market_cap is None
    assert cfg.min_avg_volume_90d is None
    assert cfg.min_pe is None
    assert cfg.sectors == ()


def test_partial_optional_filters_are_supported(tmp_path: Path):
    cfg_path = tmp_path / "partial.ini"
    cfg_path.write_text(
        """[General]
PresetName = Partial
AssetType = STOCKS
MinScore = 0

[TradingView]
StockFilterSchema = 2
Limit = 1000
OrderBy = market_cap_basic
Ascending = true

[Filters]
market = market=switzerland
market_cap_basic|above = market_cap_basic|above|100000000
""",
        encoding="utf-8",
    )
    cfg = load_screen_config(cfg_path)
    assert cfg.min_market_cap == 100000000.0
    assert cfg.min_avg_volume_90d is None
    assert cfg.min_pe is None
    assert cfg.sectors == ()


def test_primary_only_flag(tmp_path):
    p = tmp_path / "primary.ini"
    p.write_text("""[TradingView]
StockFilterSchema=2
Limit=1000
OrderBy=market_cap_basic
Ascending=false
PrimaryOnly=true

[Filters]
market=market=switzerland
""", encoding="utf-8")
    cfg = load_screen_config(p)
    assert cfg.primary_only is True
    assert cfg.min_market_cap is None


def test_pagination_flags(tmp_path):
    p = tmp_path / "full.ini"
    p.write_text("""[TradingView]
StockFilterSchema=2
Limit=4000
Paginate=true
PaginationRetries=2
PaginationOverlap=384
PaginationConfirmPasses=2
OrderBy=name
Ascending=true

[Filters]
market=market=germany
""", encoding="utf-8")
    cfg = load_screen_config(p)
    assert cfg.paginate is True
    assert cfg.limit == 4000
    assert cfg.pagination_retries == 2
    assert cfg.pagination_overlap == 384
    assert cfg.pagination_confirm_passes == 2
    assert cfg.order_by == "name"
    assert cfg.ascending is True


def test_complete_universe_flag(tmp_path):
    p = tmp_path / "full.ini"
    p.write_text("""\n[General]\nPresetName=x\nAssetType=STOCKS\nMinScore=0\n[TradingView]\nStockFilterSchema=2\nLimit=100000\nPaginate=false\nRequireCompleteUniverse=true\nOrderBy=name\nAscending=true\n[Filters]\nmarket=market=germany\n""", encoding="utf-8")
    cfg = load_screen_config(p)
    assert cfg.paginate is False
    assert cfg.require_complete_universe is True
    assert cfg.limit == 100000

import pytest


@pytest.mark.parametrize(
    ("filename", "market"),
    [
        ("identity_coverage_ireland.ini", "ireland"),
        ("identity_coverage_hongkong.ini", "hongkong"),
        ("identity_coverage_japan.ini", "japan"),
        ("identity_coverage_korea.ini", "korea"),
    ],
)
def test_regional_discovery_coverage_presets(filename, market):
    cfg_path = Path(__file__).resolve().parents[1] / "config" / filename
    cfg = load_screen_config(cfg_path)
    assert cfg.market == market
    assert cfg.limit == 4000
    assert cfg.order_by == "market_cap_basic"
    assert cfg.ascending is False
    assert cfg.primary_only is False
    assert cfg.paginate is False
    assert cfg.require_complete_universe is False
    assert cfg.min_market_cap is None
    assert cfg.min_avg_volume_90d is None
    assert cfg.min_pe is None
    assert cfg.sectors == ()
