from clr.pipeline import validate_asset

def test_synthetic_point_accepted():
    ok,reason=validate_asset({"latitude":24.0,"longitude":90.4,"coordinate_source":"SYNTHETIC_TEST_POINT"})
    assert ok and reason=="TEST_POINT"

def test_exact_site_required_for_fine_resolution():
    a={"latitude":24.0,"longitude":90.4,"coordinate_status":"RESOLVED","site_identity_grade":"PROBABLE_SITE"}
    ok,reason=validate_asset(a,require_exact_site=True)
    assert not ok and reason=="SITE_IDENTITY_NOT_EXACT"

def test_exact_site_passes():
    a={"latitude":24.0,"longitude":90.4,"coordinate_status":"RESOLVED","site_identity_grade":"EXACT_SITE"}
    ok,reason=validate_asset(a,require_exact_site=True)
    assert ok
