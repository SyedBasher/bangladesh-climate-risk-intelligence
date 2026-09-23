import networkx as nx

from clr.logistics import baseline_route, edge_disjoint_count


def test_edge_disjoint_count_respects_direction():
    G=nx.DiGraph()
    G.add_edge("A","B",length_m=1)
    G.add_edge("B","D",length_m=1)
    G.add_edge("A","C",length_m=1)
    G.add_edge("C","D",length_m=1)
    assert edge_disjoint_count(G,"A","D")==2
    assert edge_disjoint_count(G,"D","A")==0


def test_baseline_route_uses_directed_shortest_path():
    G=nx.DiGraph()
    G.add_edge("A","B",length_m=1)
    G.add_edge("B","D",length_m=1)
    G.add_edge("A","D",length_m=5)
    r=baseline_route(G,"A","D")
    assert r["nodes"]==["A","B","D"]
    assert r["length"]==2
