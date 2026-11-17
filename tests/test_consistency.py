"""Tests for the MRZ / consistency rules (Phase 5). The MRZ is ICAO 9303's own TD3 specimen."""

import pandas as pd
import pytest

from ekyc import consistency

LINE0 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
LINE1 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
SPECIMEN = {"surname": "Eriksson", "given_names": "Anna Maria", "birth_date": "12.08.1974", "issue_date": "16.04.2007",
            "expiry_date": "15.04.2012", "document_number": "L898902C3", "mrz_line0": LINE0, "mrz_line1": LINE1}


def status(fields, doc_type="srb_passport"):
    return {r.rule: r.status for r in consistency.run_rules(fields, doc_type)}


def test_check_digit_on_the_icao_specimen():
    assert consistency.check_digit("L898902C3") == "6"
    assert consistency.check_digit("740812") == "2" and consistency.check_digit("120415") == "9"
    assert consistency.check_digit("ZE184226B<<<<<") == "1"
    mrz = consistency.parse_td3(LINE0, LINE1)
    assert (mrz.surname, mrz.given_names, mrz.number, mrz.birth, mrz.expiry) == \
        ("ERIKSSON", "ANNA MARIA", "L898902C3", "740812", "120415")


def test_a_consistent_document_passes_every_rule():
    assert set(status(SPECIMEN).values()) == {"pass"}


@pytest.mark.parametrize("change, failing", [
    ({"surname": "Eriksen"}, {"mrz_vs_surname"}),
    ({"birth_date": "13.08.1974"}, {"mrz_vs_birth_date"}),
    ({"document_number": "L898902C4"}, {"mrz_vs_document_number"}),
    ({"expiry_date": "15.04.2013"}, {"mrz_vs_expiry_date"}),
    ({"mrz_line1": LINE1[:9] + "7" + LINE1[10:]}, {"mrz_check_document_number", "mrz_check_composite"}),
    ({"issue_date": "16.04.2013"}, {"date_order"}),  # issued after expiry
    ({"issue_date": "31.02.2007"}, {"dates_parseable"}),
])
def test_each_rule_catches_its_inconsistency(change, failing):
    result = status({**SPECIMEN, **change})
    assert {r for r, s in result.items() if s == "fail"} == failing


def test_given_names_truncation_only_when_the_name_field_is_full():
    # the MRZ has room left, so a name it does not contain is a real mismatch
    assert status({**SPECIMEN, "given_names": "Anna Maria Louise"})["mrz_vs_given_names"] == "fail"
    # 39 characters of names, no filler left: ICAO cuts the rest off (here mid-word, after "K")
    full = "P<UTO" + "ERIKSSON<<ANNA<MARIA<LOUISE<ELISABETH<KATHARINA"[:39]
    long_name = {**SPECIMEN, "mrz_line0": full, "given_names": "Anna Maria Louise Elisabeth Katharina"}
    assert status(long_name)["mrz_vs_given_names"] == "pass"
    assert status({**long_name, "given_names": "Anna Maria Louise Elisabeth Margaretha"})["mrz_vs_given_names"] == "fail"
    assert status({**SPECIMEN, "surname": "Eriksšon"})["mrz_vs_surname"] == "pass"  # š -> S, as on real MRZs


def test_line1_filler_miscount_is_repaired_but_data_errors_are_not():
    one_more = LINE1[:37] + "<" + LINE1[37:]  # 45 characters: an extra '<' in the personal-number field
    assert consistency.repair_line1_fillers(one_more) == (LINE1, True)
    results = {r.rule: r for r in consistency.run_rules({**SPECIMEN, "mrz_line1": one_more}, "srb_passport")}
    assert results["mrz_format"].detail == "line 2 filler count repaired"
    assert {r.status for r in results.values()} == {"pass"}
    wrong_data = LINE1[:30] + "X" + LINE1[30:]  # 45 characters, but an extra DATA character: check digits fail
    failed = {r for r, s in status({**SPECIMEN, "mrz_line1": wrong_data}).items() if s == "fail"}
    assert failed and failed <= {"mrz_check_composite", "mrz_format"}


def test_skips_and_levels(monkeypatch):
    no_mrz = status({"birth_date": "01.01.1990", "expiry_date": "01.01.2030"}, doc_type="alb_id")
    assert all(no_mrz[r] == "skip" for r in consistency.MRZ_RULES) and no_mrz["date_order"] == "pass"
    assert status({**SPECIMEN, "mrz_line1": LINE1[:40]})["mrz_format"] == "fail"  # wrong length: cannot parse
    monkeypatch.setitem(consistency.RULE_LEVEL_OVERRIDES, ("date_order", "srb_passport"), "info")
    results = consistency.run_rules({**SPECIMEN, "issue_date": "16.04.2013"}, "srb_passport")
    assert consistency.failed_flags(results) == []  # the only failure is now info-level
    table = consistency.rules_table(pd.DataFrame([{**SPECIMEN, "doc_type": "srb_passport"}], index=["d1"]))
    assert len(table) == len(consistency.RULES) and set(table["status"]) == {"pass"}
