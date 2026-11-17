"""Tests for the canonical schema, the per-type mapping and the comparison normalisation (Phase 5)."""

import pandas as pd
import pytest
from pydantic import ValidationError

from ekyc import config, schemas


def test_mapping_covers_every_type_and_only_known_fields():
    table = schemas.mapping_table()
    assert list(table.index) == list(config.DOC_TYPES) and list(table.columns) == list(schemas.CANONICAL_FIELDS)
    assert schemas.MRZ_DOC_TYPES == ("aze_passport", "grc_passport", "lva_passport", "srb_passport")
    # the number trap: esp_id swaps the meaning of number / id_number compared with alb_id
    assert schemas.DOC_FIELD_MAP["esp_id"]["document_number"] == "id_number"
    assert schemas.DOC_FIELD_MAP["alb_id"]["document_number"] == "number"
    assert schemas.canonical_of("esp_id", "number") == "personal_number"
    assert schemas.canonical_of("fin_id", "code") == "personal_number" and schemas.canonical_of("alb_id", "photo") is None


def test_ground_truth_table_joins_and_renames():
    gt = pd.DataFrame([("esp_id_01", "surname", "CALERO"), ("esp_id_01", "surname_second", "CONDE"),
                       ("esp_id_01", "number", "48518051Y"), ("esp_id_01", "id_number", "AXT103442"),
                       ("fin_id_01", "birth_date_2", "010481"), ("fin_id_01", "code", "-927N"),
                       ("grc_passport_01", "surname", "ΠΑΠΑΓΟΣ"), ("grc_passport_01", "surname_eng", "PAPAGO")],
                      columns=["doc_id", "field_name", "value"])
    table = schemas.ground_truth_table(gt)
    assert table.loc["esp_id_01", "surname"] == "CALERO CONDE"
    assert table.loc["esp_id_01", "document_number"] == "AXT103442" and table.loc["esp_id_01", "personal_number"] == "48518051Y"
    assert table.loc["fin_id_01", "personal_number"] == "010481-927N"  # joined without a space
    assert table.loc["grc_passport_01", "surname"] == "PAPAGO"  # the Latin line, as in the MRZ


@pytest.mark.parametrize("text, field, iso", [
    ("20-11-1991", "birth_date", "1991-11-20"), ("14.08.1994", "birth_date", "1994-08-14"),
    ("28.09.1974.", "birth_date", "1974-09-28"), ("01. 04. 1981", "birth_date", "1981-04-01"),
    ("31 01 1971", "birth_date", "1971-01-31"), ("02 Jan 87", "birth_date", "1987-01-02"),
    ("13 Okt 74", "birth_date", "1974-10-13"), ("27 Mar 24", "expiry_date", "2024-03-27"),
    ("140915", "issue_date", "2015-09-14"), ("1991-11-20", "birth_date", "1991-11-20"),
    ("31.02.1990", "birth_date", None), ("soon", "birth_date", None), (None, "birth_date", None)])
def test_parse_date(text, field, iso):
    assert schemas.parse_date(text, field) == iso


def test_normalisation_rules():
    assert [schemas.normalize_gender(g) for g in ("K/M", "Q/F", "V/M", "S/F", "M / M", "Ž / F", "Ž", "МУЖ.", "ЖЕН.")] == \
        ["M", "F", "M", "F", "M", "F", "F", "M", "F"]
    assert schemas.normalize_value("birth_date", "02 Jan 87") == schemas.normalize_value("birth_date", "02.01.1987")
    assert schemas.normalize_value("document_number", "45    98 647461") == "4598647461"
    assert schemas.normalize_value("surname", "  Mikuš ") == "mikuš" != schemas.normalize_value("surname", "Mikus")
    assert schemas.normalize_value("authority", "Α.Ε.Α.") == schemas.normalize_value("authority", "A.E.A.")  # homoglyphs
    assert schemas.normalize_value("mrz_line0", "P<GRCX<<Y<<<<<") == schemas.normalize_value("mrz_line0", "P<GRCX<<Y<<")
    assert schemas.normalize_value("mrz_line1", "AB1<<") != schemas.normalize_value("mrz_line1", "AB1<")  # positional


def test_cer_and_compare_fields():
    assert schemas.levenshtein("kitten", "sitting") == 3
    assert schemas.cer("ABCD", "ABCE") == 0.25 and schemas.cer(None, "ABC") == 1.0
    rows = schemas.compare_fields({"surname": "agani", "birth_date": "20.11.1991", "mrz_line0": "P<X"},
                                  {"surname": "Agani", "birth_date": "20-11-1991", "gender": "M"}).set_index("field")
    assert not rows.loc["surname", "exact"] and rows.loc["surname", "normalized"]  # case only
    assert rows.loc["birth_date", "normalized"] and rows.loc["birth_date", "cer"] == 0
    assert not rows.loc["gender", "normalized"] and rows.loc["gender", "cer"] == 1.0  # missing prediction
    assert rows.loc["mrz_line0", "spurious"]  # filled although the truth has no MRZ


def test_idfields_validation():
    f = schemas.IDFields.model_validate({"surname": "  Agani ", "gender": "", "mrz_line0": "p<srbzebic<<đurica<<"})
    assert f.surname == "Agani" and f.gender is None
    assert f.mrz_line0 == "P<SRBZEBIC<<DURICA<<"  # upper case, Đ written as D (as on real MRZs)
    with pytest.raises(ValidationError):
        schemas.IDFields.model_validate({"mrz_line1": "AB12#34"})  # not an MRZ character
    with pytest.raises(ValidationError):
        schemas.IDFields.model_validate({"height": "175"})  # unknown key
