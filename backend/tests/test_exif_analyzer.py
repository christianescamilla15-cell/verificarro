"""Tests del exif_analyzer. Pure — no red, no Pillow disk."""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image

from app.analyzers.exif_analyzer import (
    ExifMetadata,
    analyze_batch,
    extract_metadata,
)


# ---------------------------------------------------------------------------
# Helpers


def _img_with_exif(**exif_tags) -> bytes:
    """Genera un JPEG con la EXIF que pidamos. Útil para tests."""
    from PIL import ExifTags

    img = Image.new("RGB", (10, 10), color=(127, 127, 127))
    exif = img.getexif()
    # Mapear nombres legibles → tag IDs
    name_to_id = {name: tid for tid, name in ExifTags.TAGS.items()}
    for name, val in exif_tags.items():
        if name in name_to_id:
            exif[name_to_id[name]] = val
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def _img_no_exif() -> bytes:
    img = Image.new("RGB", (10, 10), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_metadata


def test_extract_metadata_none_bytes_returns_no_exif() -> None:
    out = extract_metadata(None)
    assert out.has_exif is False


def test_extract_metadata_empty_bytes_returns_no_exif() -> None:
    out = extract_metadata(b"")
    assert out.has_exif is False


def test_extract_metadata_image_without_exif() -> None:
    out = extract_metadata(_img_no_exif())
    assert out.has_exif is False


def test_extract_metadata_image_with_software() -> None:
    img = _img_with_exif(Software="Adobe Photoshop CC 2024")
    out = extract_metadata(img)
    assert out.has_exif is True
    assert out.software == "Adobe Photoshop CC 2024"


def test_extract_metadata_image_with_datetime_original() -> None:
    img = _img_with_exif(DateTimeOriginal="2020:06:15 12:34:56")
    out = extract_metadata(img)
    assert out.has_exif is True
    assert out.datetime_original == datetime(2020, 6, 15, 12, 34, 56)


def test_extract_metadata_invalid_datetime_string_ignored() -> None:
    img = _img_with_exif(DateTimeOriginal="garbage value")
    out = extract_metadata(img)
    assert out.datetime_original is None


def test_extract_metadata_invalid_jpeg_returns_no_exif() -> None:
    out = extract_metadata(b"not a real jpeg, just garbage bytes")
    assert out.has_exif is False


# ---------------------------------------------------------------------------
# analyze_batch


def _meta(**kwargs) -> ExifMetadata:
    defaults = dict(has_exif=True)
    defaults.update(kwargs)
    return ExifMetadata(**defaults)


def test_analyze_batch_empty_input_returns_empty() -> None:
    assert analyze_batch([]) == []


def test_analyze_batch_detects_photoshop_edit() -> None:
    metadatas = [_meta(software="Adobe Photoshop 24.0")]
    findings = analyze_batch(metadatas)
    assert any(f.flag == "edited_software" and f.severity == "medium" for f in findings)
    assert any("Photoshop" in f.note for f in findings)


def test_analyze_batch_detects_gimp_edit() -> None:
    metadatas = [_meta(software="GIMP 2.10.32")]
    findings = analyze_batch(metadatas)
    assert any(f.flag == "edited_software" for f in findings)


def test_analyze_batch_detects_ai_tool_edit() -> None:
    metadatas = [_meta(software="Topaz Photo AI 4.5")]
    findings = analyze_batch(metadatas)
    assert any(f.flag == "edited_software" for f in findings)


def test_analyze_batch_camera_software_no_alert() -> None:
    """Software como 'iPhone 14 Pro 17.1' o 'Samsung S23' NO debería
    disparar edit alert — son fields de cámara nativa."""
    metadatas = [_meta(software="iPhone 14 Pro 17.1")]
    findings = analyze_batch(metadatas)
    assert not any(f.flag == "edited_software" for f in findings)


def test_analyze_batch_old_photo_vs_recent_listing() -> None:
    """Foto del 2018 en un listing del 2025 = old_photo low alert."""
    old_dt = datetime(2018, 3, 1, 10, 0, 0)
    metadatas = [_meta(datetime_original=old_dt)]
    findings = analyze_batch(metadatas, listing_year=2025)
    assert any(
        f.flag == "old_photo" and f.severity == "low" for f in findings
    )


def test_analyze_batch_recent_photo_no_alert() -> None:
    recent_dt = datetime(2024, 11, 1, 10, 0, 0)
    metadatas = [_meta(datetime_original=recent_dt)]
    findings = analyze_batch(metadatas, listing_year=2025)
    assert not any(f.flag == "old_photo" for f in findings)


def test_analyze_batch_duplicate_timestamp_in_3_or_more_photos() -> None:
    """3 fotos con el mismo timestamp = batch fake / dump."""
    same_dt = datetime(2024, 5, 1, 10, 0, 0)
    metadatas = [
        _meta(datetime_original=same_dt),
        _meta(datetime_original=same_dt),
        _meta(datetime_original=same_dt),
        _meta(datetime_original=datetime(2024, 5, 1, 10, 1, 0)),
    ]
    findings = analyze_batch(metadatas)
    dup = [f for f in findings if f.flag == "duplicate_timestamp"]
    assert len(dup) == 1
    assert dup[0].severity == "medium"
    assert "3 fotos comparten" in dup[0].note


def test_analyze_batch_two_same_timestamp_no_alert() -> None:
    """2 fotos con mismo timestamp es común (rapid-fire phone shutter), no alertar."""
    same_dt = datetime(2024, 5, 1, 10, 0, 0)
    metadatas = [
        _meta(datetime_original=same_dt),
        _meta(datetime_original=same_dt),
    ]
    findings = analyze_batch(metadatas)
    assert not any(f.flag == "duplicate_timestamp" for f in findings)


def test_analyze_batch_no_exif_anywhere_emits_low_info() -> None:
    metadatas = [
        ExifMetadata(has_exif=False),
        ExifMetadata(has_exif=False),
        ExifMetadata(has_exif=False),
    ]
    findings = analyze_batch(metadatas)
    assert any(f.flag == "no_exif_anywhere" and f.severity == "low" for f in findings)


def test_analyze_batch_some_with_exif_no_anywhere_alert() -> None:
    """Si AL MENOS UNA foto tiene EXIF, no emitimos no_exif_anywhere."""
    metadatas = [
        ExifMetadata(has_exif=False),
        _meta(software="iPhone"),
    ]
    findings = analyze_batch(metadatas)
    assert not any(f.flag == "no_exif_anywhere" for f in findings)


def test_analyze_batch_photo_index_correctness() -> None:
    """El photo_index debe corresponder a la posición en la lista de entrada."""
    metadatas = [
        _meta(),  # idx 0
        _meta(software="Adobe Photoshop"),  # idx 1
        _meta(),  # idx 2
    ]
    findings = analyze_batch(metadatas)
    edit_findings = [f for f in findings if f.flag == "edited_software"]
    assert len(edit_findings) == 1
    assert edit_findings[0].photo_index == 1
