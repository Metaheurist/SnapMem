import json
import zipfile

from sc_memories_downloader.importer import classify_inputs, find_memories_json, is_memories_json


def _memories_json(path, n=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"Saved Media": [{"Date": "2023-05-01 18:22:05 UTC", "Media Type": "Image", "Download Link": ""}] * n}), encoding="utf-8")
    return path


def _zip(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("memories/a.jpg", b"1")
    return path


def test_zip_file(tmp_path):
    z = _zip(tmp_path / "mydata~1.zip")
    sel = classify_inputs([z])
    assert sel.zip_files == [z.resolve()] and not sel.errors


def test_folder_with_export_zips(tmp_path):
    a = _zip(tmp_path / "mydata~1.zip")
    b = _zip(tmp_path / "mydata~2.zip")
    (tmp_path / "other.zip").write_bytes(b"x")
    sel = classify_inputs([tmp_path])
    assert sel.zip_files == [a.resolve(), b.resolve()]
    assert not sel.export_dirs


def test_extracted_export_folder(tmp_path):
    root = tmp_path / "export"
    (root / "memories").mkdir(parents=True)
    (root / "memories" / "a.jpg").write_bytes(b"1")
    sel = classify_inputs([root])
    assert sel.export_dirs == [root.resolve()]


def test_memories_json(tmp_path):
    j = _memories_json(tmp_path / "memories_history.json")
    sel = classify_inputs([j])
    assert sel.memories_json == j.resolve()
    assert is_memories_json(j)


def test_errors_are_collected(tmp_path):
    bad_json = tmp_path / "other.json"
    bad_json.write_text('{"x": 1}', encoding="utf-8")
    bad_zip = tmp_path / "broken.zip"
    bad_zip.write_bytes(b"nope")
    empty = tmp_path / "empty"
    empty.mkdir()
    text = tmp_path / "notes.txt"
    text.write_text("hi", encoding="utf-8")
    sel = classify_inputs([bad_json, bad_zip, empty, text, tmp_path / "missing.zip"])
    assert sel.empty
    assert len(sel.errors) == 5


def test_only_one_memories_json(tmp_path):
    a = _memories_json(tmp_path / "a" / "memories_history.json")
    b = _memories_json(tmp_path / "b" / "memories_history.json")
    sel = classify_inputs([a, b])
    assert sel.memories_json == a.resolve()
    assert len(sel.errors) == 1


def test_find_memories_json(tmp_path):
    _memories_json(tmp_path / "x" / "json" / "memories_history.json")
    assert find_memories_json(tmp_path).name == "memories_history.json"
    assert find_memories_json(tmp_path / "x" / "nothing") is None
