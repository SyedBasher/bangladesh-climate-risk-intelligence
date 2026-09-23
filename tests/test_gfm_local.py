import pandas as pd
import pytest

import clr.gfm_local as gfm


ASSETS = [
    {"asset_location_id":"A","tenant_key":"INTERNAL","external_system":"SYNTH","external_id":"A","latitude":24.0,"longitude":90.4},
    {"asset_location_id":"B","tenant_key":"INTERNAL","external_system":"SYNTH","external_id":"B","latitude":24.1,"longitude":90.5},
    {"asset_location_id":"C","tenant_key":"INTERNAL","external_system":"SYNTH","external_id":"C","latitude":24.2,"longitude":90.6},
    {"asset_location_id":"D","tenant_key":"INTERNAL","external_system":"SYNTH","external_id":"D","latitude":24.3,"longitude":90.7},
]


def _item():
    return {
        "id":"GFM_SYNTH_1",
        "properties":{"datetime":"2025-07-15T06:00:00Z"},
        "assets":{
            "ensemble_flood_extent":{"href":"flood"},
            "exclusion_mask":{"href":"exclude"},
            "reference_water_mask":{"href":"reference"},
            "ensemble_likelihood":{"href":"likelihood"},
            "advisory_flags":{"href":"advisory"},
        },
    }


def test_gfm_masks_define_eligible_acquisitions_but_advisory_does_not(monkeypatch):
    values={
        "flood":[1,1,1,0],
        "exclude":[0,1,0,0],
        "reference":[0,0,1,0],
        "likelihood":[80,70,60,0],
        "advisory":[1,0,0,0],
    }
    monkeypatch.setattr(gfm,"_sample_href",lambda href,assets: values[href])

    frame=gfm.sample_gfm_items([_item()],ASSETS)
    by_id={r["external_id"]:r for r in frame.to_dict(orient="records")}

    assert by_id["A"]["eligible"] is True
    assert by_id["A"]["flood_positive"] is True
    assert by_id["A"]["advisory_flagged"] is True

    assert by_id["B"]["eligible"] is False
    assert by_id["B"]["flood_positive"] is False

    assert by_id["C"]["eligible"] is False
    assert by_id["C"]["flood_positive"] is False

    assert by_id["D"]["eligible"] is True
    assert by_id["D"]["flood_positive"] is False


def test_gfm_rate_denominator_is_eligible_acquisitions_not_days(monkeypatch):
    values={
        "flood":[1,1,1,0],
        "exclude":[0,1,0,0],
        "reference":[0,0,1,0],
        "likelihood":[80,70,60,0],
        "advisory":[1,0,0,0],
    }
    monkeypatch.setattr(gfm,"_sample_href",lambda href,assets: values[href])
    summary=gfm.summarize_gfm_event(
        gfm.sample_gfm_items([_item()],ASSETS),
        assets=ASSETS,
    ).set_index("external_id")

    assert summary.loc["A","gfm_eligible_acquisition_count"] == 1
    assert summary.loc["A","gfm_flood_positive_acquisition_count"] == 1
    assert summary.loc["A","gfm_flood_positive_acquisition_rate"] == 1.0

    assert summary.loc["D","gfm_eligible_acquisition_count"] == 1
    assert summary.loc["D","gfm_flood_positive_acquisition_count"] == 0
    assert summary.loc["D","gfm_flood_positive_acquisition_rate"] == 0.0

    assert summary.loc["B","gfm_eligible_acquisition_count"] == 0
    assert pd.isna(summary.loc["B","gfm_flood_positive_acquisition_rate"])
    assert summary.loc["B","quality_flag"] == "NO_ELIGIBLE_ACQUISITIONS"


def test_no_stac_items_still_preserves_each_asset_as_zero_evidence():
    empty=pd.DataFrame(columns=[
        "asset_location_id","tenant_key","external_system","external_id","item_id",
        "observed_at","ensemble_flood_extent","exclusion_mask","reference_water_mask",
        "ensemble_likelihood","advisory_flags","covered","eligible",
        "flood_positive","advisory_flagged",
    ])
    summary=gfm.summarize_gfm_event(empty,assets=ASSETS)
    assert len(summary)==4
    assert set(summary["gfm_eligible_acquisition_count"])=={0}
    assert summary["gfm_flood_positive_acquisition_rate"].isna().all()


@pytest.mark.parametrize(
    "depth,eligible,positive,expected",
    [
        (0.8,2,1,"MODELLED_AND_OBSERVED"),
        (0.0,2,1,"OBSERVED_FLOOD_REVIEW_MODELLED_POINT_HAZARD"),
        (0.8,2,0,"MODELLED_NO_GFM_DETECTION_IN_WINDOW"),
        (0.0,2,0,"NO_GFM_DETECTION_AND_NO_MODELLED_POINT_DEPTH"),
        (None,2,1,"OBSERVED_FLOOD_MODELLED_POINT_VALUE_UNAVAILABLE"),
        (None,2,0,"NO_GFM_DETECTION_MODELLED_POINT_VALUE_UNAVAILABLE"),
        (None,0,0,"NO_COMPARABLE_EVENT_EVIDENCE"),
        (0.8,0,0,"NO_ELIGIBLE_GFM_EVIDENCE"),
    ],
)
def test_jrc_gfm_relation_is_bounded(depth,eligible,positive,expected):
    assert gfm.evidence_relation(depth,eligible,positive)==expected
