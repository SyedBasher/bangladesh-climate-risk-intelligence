from __future__ import annotations
import math
import networkx as nx

def _weight(G, u, v, data, field):
    val=data.get(field)
    if val is None:
        raise ValueError(f"Edge {(u,v)} missing required weight {field}")
    val=float(val)
    if val < 0:
        raise ValueError("Negative edge weight is not allowed")
    return val

def route_nodes(G: nx.Graph, origin, destination, weight="length_m"):
    return nx.shortest_path(G, origin, destination, weight=weight)

def route_edges(nodes):
    return list(zip(nodes[:-1], nodes[1:]))

def route_length(G: nx.Graph, nodes, weight="length_m"):
    total=0.0
    for u,v in route_edges(nodes):
        data=G.get_edge_data(u,v)
        if G.is_multigraph():
            vals=[_weight(G,u,v,d,weight) for d in data.values()]
            total += min(vals)
        else:
            total += _weight(G,u,v,data,weight)
    return total

def baseline_route(G, origin, destination, weight="length_m"):
    nodes=route_nodes(G,origin,destination,weight)
    return {"nodes":nodes,"edges":route_edges(nodes),"length":route_length(G,nodes,weight)}

def prune_hazard_edges(G: nx.Graph, blocked_attr="hazard_blocked"):
    H=G.copy(); remove=[]
    if H.is_multigraph():
        for u,v,k,d in H.edges(keys=True,data=True):
            if bool(d.get(blocked_attr,False)): remove.append((u,v,k))
        H.remove_edges_from(remove)
    else:
        for u,v,d in H.edges(data=True):
            if bool(d.get(blocked_attr,False)): remove.append((u,v))
        H.remove_edges_from(remove)
    return H

def hazard_conditioned_connectivity(G, origin, destination, weight="length_m", blocked_attr="hazard_blocked"):
    base=baseline_route(G,origin,destination,weight); H=prune_hazard_edges(G,blocked_attr)
    try:
        alt=baseline_route(H,origin,destination,weight); exists=True
        ratio=None if base["length"]==0 else alt["length"]/base["length"]
    except nx.NetworkXNoPath:
        alt=None; exists=False; ratio=None
    return {"baseline_length":base["length"],"hazard_free_route_exists":exists,"hazard_avoiding_length":None if alt is None else alt["length"],"hazard_detour_ratio":ratio,"isolation_flag":not exists}

def edge_disjoint_count(G, origin, destination, cap=10):
    H=nx.Graph(); H.add_nodes_from(G.nodes); H.add_edges_from((u,v) for u,v in G.edges())
    try:
        gen=nx.edge_disjoint_paths(H,origin,destination); n=0
        for _ in gen:
            n+=1
            if n>=cap: break
        return n
    except nx.NetworkXNoPath:
        return 0

def redundancy_metrics(G, origin, destination, blocked_attr="hazard_blocked", cap=10):
    base=edge_disjoint_count(G,origin,destination,cap); H=prune_hazard_edges(G,blocked_attr); post=edge_disjoint_count(H,origin,destination,cap)
    return {"edge_disjoint_route_count":base,"edge_disjoint_route_count_after_hazard":post,"route_redundancy_loss":base-post}

def route_exposure(G, nodes, exposed_attr="hazard_exposed", weight="length_m"):
    total=0.0; exposed=0.0
    for u,v in route_edges(nodes):
        data=G.get_edge_data(u,v)
        if G.is_multigraph():
            candidates=list(data.values()); d=min(candidates,key=lambda x: float(x.get(weight,math.inf)))
        else:
            d=data
        length=_weight(G,u,v,d,weight); total += length
        if bool(d.get(exposed_attr,False)): exposed += length
    return {"route_length":total,"hazard_exposed_route_length":exposed,"hazard_exposed_route_share":None if total==0 else exposed/total}

def single_edge_cut_count(G, origin, destination):
    if not nx.has_path(G,origin,destination): return None
    count=0
    for e in list(G.edges()):
        H=G.copy(); H.remove_edge(*e)
        if not nx.has_path(H,origin,destination): count += 1
    return count

def shared_edge_asset_counts(asset_routes: dict[str,list]):
    counts={}
    for asset,edges in asset_routes.items():
        seen=set()
        for u,v in edges: seen.add(tuple(sorted((u,v),key=str)))
        for key in seen: counts[key]=counts.get(key,0)+1
    return counts

def shared_hazard_bottlenecks(G, asset_routes: dict[str,list], exposed_attr="hazard_exposed"):
    counts=shared_edge_asset_counts(asset_routes); out=[]
    for edge,n in counts.items():
        u,v=edge
        if not G.has_edge(u,v): continue
        d=G.get_edge_data(u,v)
        exposed=any(bool(x.get(exposed_attr,False)) for x in d.values()) if G.is_multigraph() else bool(d.get(exposed_attr,False))
        if exposed and n>1: out.append({"edge":edge,"asset_count":n})
    return sorted(out,key=lambda x:(-x["asset_count"],str(x["edge"])))
