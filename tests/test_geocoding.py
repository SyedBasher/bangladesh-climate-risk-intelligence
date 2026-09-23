from clr.geocoding import build_queries, candidate_grade

def row():
    return {"name_en":"Example Factory Ltd","name_bn":"","full_address_dife":"Karnogop, Barpa","upazila_dife":"Rupganj","district_dife":"Narayanganj"}

def test_queries_never_name_only():
    qs=build_queries(row())
    assert len(qs)==2
    assert all("Narayanganj" in q["q"] and "Bangladesh" in q["q"] for q in qs)

def test_admin_mismatch_hard_reject():
    c={"display_name":"Example Factory, Gazipur","class":"place","type":"industrial","address":{"district":"Gazipur"}}
    grade,reasons=candidate_grade(row(),c,False)
    assert grade=="REJECTED_ADMIN_MISMATCH"

def test_locality_only_not_site():
    c={"display_name":"Rupganj, Narayanganj, Bangladesh","class":"place","type":"town","address":{"town":"Rupganj","district":"Narayanganj"}}
    grade,reasons=candidate_grade(row(),c,False)
    assert grade=="LOCALITY_ONLY"

def test_probable_site_requires_site_evidence():
    c={"display_name":"Example Factory Ltd, Karnogop, Rupganj, Narayanganj","name":"Example Factory Ltd","class":"man_made","type":"works","address":{"town":"Rupganj","district":"Narayanganj"}}
    grade,reasons=candidate_grade(row(),c,True)
    assert grade=="PROBABLE_SITE"
