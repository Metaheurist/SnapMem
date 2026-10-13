import json

from sc_memories_downloader.settings import Settings, load_settings, save_settings, settings_path


def test_round_trip(tmp_path):
    s = Settings(output_dir=str(tmp_path), layout="year", file_mode="copy", delete_extracted=True, max_zip_downloads=3, max_memory_downloads=8, rate_limit_mb_s=2.5, min_request_gap_ms=500, keep_signed_in=True, write_urls_file=True)
    path = save_settings(s, tmp_path / "settings.json")
    assert load_settings(path) == s


def test_default_path_uses_snapmem_home(isolated_home):
    save_settings(Settings(layout="flat"))
    assert settings_path() == isolated_home / "settings.json"
    assert load_settings().layout == "flat"


def test_values_are_clamped_and_validated():
    s = Settings(layout="random", file_mode="delete", max_zip_downloads=99, max_memory_downloads=0, rate_limit_mb_s=-4, min_request_gap_ms="x").normalized()
    assert s.layout == "year_month"
    assert s.file_mode == "move"
    assert s.max_zip_downloads == 6
    assert s.max_memory_downloads == 1
    assert s.rate_limit_mb_s == 0
    assert s.min_request_gap_ms == 250


def test_bad_files_fall_back_to_defaults(tmp_path):
    p = tmp_path / "settings.json"
    assert load_settings(p) == Settings()
    p.write_text("{not json", encoding="utf-8")
    assert load_settings(p) == Settings()
    p.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(p) == Settings()
    p.write_text(json.dumps({"layout": "year", "unknown_key": 1}), encoding="utf-8")
    assert load_settings(p).layout == "year"
