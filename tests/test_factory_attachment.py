from clr.factory_attachment import fine_hazard_allowed, attach_hazard, scale_exposure, missing_data_questions
from clr.era5_validation_gateway import era5_land_validation_url

def asset():
    return {"external_id":"X","site_identity_grade":"EXACT_SITE","coordinate_status":"RESOLVED","worker_total":1500,"machine_count_external":750,"annual_capacity_external":300000,"sector_mapped":"RMG_WOVEN"}

def test_fine_hazard_gate():
    assert fine_hazard_allowed(asset())
    bad=dict(asset()); bad["site_identity_grade"]="PROBABLE_SITE"
    r=attach_hazard(bad,"flood_rp100_depth_m",0.6,"JRC_TEST")
    assert r["value"] is None
    assert r["quality_flag"]=="BLOCKED_GEOQUALITY"

def test_operational_scale_exposure():
    r=scale_exposure(asset(),flood_depth_m=0.5,heat_days=24)
    assert r["worker_heat_exposure_days"]==36000
    assert r["workers_at_modelled_flooded_site"]==1500
    assert r["machines_at_modelled_flooded_site"]==750
    assert r["annual_capacity_at_modelled_flooded_site"]==300000

def test_no_flood_zeroes_footprint_exposure():
    r=scale_exposure(asset(),flood_depth_m=0.0)
    assert r["workers_at_modelled_flooded_site"]==0
    assert r["machines_at_modelled_flooded_site"]==0

def test_missing_questions_are_sector_sensitive():
    q=missing_data_questions(asset(),{"HEAT","FLOOD"})
    assert any("wet processing" in x.lower() for x in q)
    assert any("equipment elevation" in x.lower() for x in q)

def test_validation_gateway_is_explicit_era5_land():
    u=era5_land_validation_url(24.0,90.4,"2025-01-01","2025-12-31")
    assert "models=era5_land" in u
    assert "timezone=Asia%2FDhaka" in u
