import networkx as nx
from clr.logistics import baseline_route, hazard_conditioned_connectivity, redundancy_metrics, route_exposure, shared_edge_asset_counts, shared_hazard_bottlenecks, single_edge_cut_count

def graph():
    G=nx.Graph()
    G.add_edge("A","B",length_m=1000,hazard_exposed=False,hazard_blocked=False)
    G.add_edge("B","D",length_m=1000,hazard_exposed=True,hazard_blocked=True)
    G.add_edge("A","C",length_m=1500,hazard_exposed=False,hazard_blocked=False)
    G.add_edge("C","D",length_m=1500,hazard_exposed=False,hazard_blocked=False)
    return G

def test_baseline_and_detour():
    G=graph(); b=baseline_route(G,"A","D"); assert b["length"]==2000
    h=hazard_conditioned_connectivity(G,"A","D")
    assert h["hazard_free_route_exists"] and h["hazard_avoiding_length"]==3000 and h["hazard_detour_ratio"]==1.5 and not h["isolation_flag"]

def test_route_exposure():
    G=graph(); b=baseline_route(G,"A","D"); e=route_exposure(G,b["nodes"])
    assert e["hazard_exposed_route_length"]==1000 and e["hazard_exposed_route_share"]==0.5

def test_redundancy_loss():
    r=redundancy_metrics(graph(),"A","D")
    assert r["edge_disjoint_route_count"]==2 and r["edge_disjoint_route_count_after_hazard"]==1 and r["route_redundancy_loss"]==1

def test_isolation_when_all_routes_blocked():
    G=graph(); G["C"]["D"]["hazard_blocked"]=True; h=hazard_conditioned_connectivity(G,"A","D")
    assert h["isolation_flag"] and h["hazard_detour_ratio"] is None

def test_shared_bottleneck():
    G=nx.Graph(); G.add_edge("A","X",length_m=1,hazard_exposed=False); G.add_edge("B","X",length_m=1,hazard_exposed=False); G.add_edge("X","Y",length_m=1,hazard_exposed=True); G.add_edge("Y","D",length_m=1,hazard_exposed=False)
    routes={"asset1":[("A","X"),("X","Y"),("Y","D")],"asset2":[("B","X"),("X","Y"),("Y","D")]}
    c=shared_edge_asset_counts(routes); assert c[("X","Y")]==2
    h=shared_hazard_bottlenecks(G,routes); assert h[0]["asset_count"]==2 and h[0]["edge"]==("X","Y")

def test_od_cut_edges():
    G=nx.Graph(); G.add_edge("A","B",length_m=1); G.add_edge("B","C",length_m=1)
    assert single_edge_cut_count(G,"A","C")==2
