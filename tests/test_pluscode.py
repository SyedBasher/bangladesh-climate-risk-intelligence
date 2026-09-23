from clr.pluscode import encode_pair_section, decode_full, recover_short

def test_full_code_roundtrip_cell():
    c=encode_pair_section(25.66661,89.3001,10)
    assert c=="7MQFM882+J2"
    a=decode_full(c)
    assert abs(a["lat_center"]-25.6665625)<1e-8
    assert abs(a["lon_center"]-89.3000625)<1e-8

def test_short_code_recovery_synthetic_reference():
    a=recover_short("M882+J2",25.66661,89.3001)
    assert abs(a["recovered_lat"]-25.6665625)<1e-8
    assert abs(a["recovered_lon"]-89.3000625)<1e-8
