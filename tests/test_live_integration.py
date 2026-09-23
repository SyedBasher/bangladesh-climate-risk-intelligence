import pandas as pd
import pytest
from clr.live_integration import SourceState, can_publish, enforce_atomic_profile, validate_indicator_rows

def profile():
    return {"publish_mode":"ATOMIC","required_sources":["A","B"],"allow_validation_gateway_values":False}

def test_atomic_profile_blocks_missing_source():
    states=[SourceState("A","COMPLETE","PRODUCTION",sha256="x"),SourceState("B","MISSING","PRODUCTION")]
    ok,missing=can_publish(profile(),states)
    assert not ok and missing==["B"]
    with pytest.raises(RuntimeError): enforce_atomic_profile(profile(),states)

def test_atomic_profile_passes_complete_sources():
    states=[SourceState("A","COMPLETE","PRODUCTION",sha256="x"),SourceState("B","COMPLETE","PRODUCTION",sha256="y")]
    ok,missing=can_publish(profile(),states)
    assert ok and missing==[]

def test_validation_only_source_cannot_enter_production():
    states=[SourceState("A","COMPLETE","VALIDATION_ONLY",sha256="x"),SourceState("B","COMPLETE","PRODUCTION",sha256="y")]
    df=pd.DataFrame([{"external_id":"1","indicator_id":"heat","value_class":"SOURCE","measurement_basis":"REANALYSIS","source_id":"A","source_vintage":"v1"}])
    with pytest.raises(ValueError): validate_indicator_rows(df,profile(),states)

def test_indicator_cannot_reference_incomplete_source():
    states=[SourceState("A","MISSING","PRODUCTION")]
    df=pd.DataFrame([{"external_id":"1","indicator_id":"heat","value_class":"SOURCE","measurement_basis":"REANALYSIS","source_id":"A","source_vintage":"v1"}])
    with pytest.raises(ValueError): validate_indicator_rows(df,{"allow_validation_gateway_values":False},states)
