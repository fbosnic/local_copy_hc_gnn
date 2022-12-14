from collections import deque
from pathlib import Path
import networkit
import networkx as nx
import torch
from copy import deepcopy
import numpy

from hamgnn.HamiltonSolver import HamiltonSolver


def _to_networkit(num_nodes, edge_index: torch.tensor):
    g = networkit.Graph(num_nodes)
    for edge in edge_index.t():
        if not g.hasEdge(*edge):
            g.addEdge(*edge)
    return g


def _least_degree_first(g: networkit.Graph, start_node, map_node_to_degree, is_use_unreachable_vertex_heuristics=True):
    g = deepcopy(g)
    current = start_node
    path = []
    for step in range(g.numberOfNodes()):
        path.append(current)
        next_step_options = sorted([x for x in g.iterNeighbors(current)], key = lambda x: map_node_to_degree[x])
        g.removeNode(current)
        if is_use_unreachable_vertex_heuristics:
            better_options = [x for x in next_step_options
                              if g.degree(x) > 0 and min([g.degree(y) for y in g.iterNeighbors(x)]) > 1]
            if better_options:
                next_step_options = better_options

        if next_step_options:
            current = next_step_options[0]
        else:
            break
    return path


def least_degree_first_heuristics(num_nodes, edge_index: torch.tensor, is_use_unreachable_vertex_heuristics=True):
    g = _to_networkit(num_nodes, edge_index)
    map_node_to_degree = {x: g.degree(x) for x in g.iterNodes()}
    max_degree = networkit.graphtools.maxDegree(g)
    start_nodes = [x for x in g.iterNodes() if g.degree(x) == max_degree]
    path = []
    for start in start_nodes:
        proposed_path = _least_degree_first(g, start, map_node_to_degree, is_use_unreachable_vertex_heuristics)
        if len(proposed_path) > len(path):
            path = proposed_path
    if len(path) == num_nodes and g.hasEdge(path[0], path[-1]):
        path.append(path[0])
    return path


def _rotational_options(g, path):
    end = path[-1]
    rotational_options = [path, _invert_path(path)]
    for i in range(len(path) - 2):
        if g.hasEdge(path[i], end):
            rotational_options.append(path[:i + 1] + [path[j] for j in range(len(path) - 1, i, -1)])
    return rotational_options


def _invert_path(path):
    return [path[i] for i in range(len(path) - 1, -1, -1)]


class LeastDegreeFirstHeuristics(HamiltonSolver):
    def solve_graphs(self, graphs):
        return [least_degree_first_heuristics(graph.num_nodes, graph.edge_index, True) for graph in graphs]


def _path_nr_extendable_nodes(graph, p):
    return len([x for x in graph.iterNeighbors(p[-1]) if x not in p])


class HybridHam(HamiltonSolver):
    def solve_graphs(self, graphs):
        return [self._solve(graph.num_nodes, graph.edge_index) for graph in graphs]

    def _solve(self, num_nodes, edge_index: torch.tensor):
        g = _to_networkit(num_nodes, edge_index)
        map_node_to_degree = {x: g.degree(x) for x in g.iterNodes()}

        path = least_degree_first_heuristics(num_nodes, edge_index, is_use_unreachable_vertex_heuristics=True)
        if len(path) <= 2:
            return path

        while len(path) < num_nodes:
            if map_node_to_degree[path[0]] > map_node_to_degree[path[-1]]:
                path = _invert_path(path)
            rotational_options = _rotational_options(g, path)
            if len(rotational_options) > 0:
                extension_options = [p for p in rotational_options if _path_nr_extendable_nodes(g, p) > 0]
                if not extension_options:
                    return path
                path = min(extension_options, key=lambda p: _path_nr_extendable_nodes(g, p))
                reduced_graph = deepcopy(g)
                for edge in g.iterEdges():
                    if edge[0] in path[:-1] or edge[1] in path[:-1]:
                        reduced_graph.removeEdge(*edge)
                extension = _least_degree_first(reduced_graph, path[-1], map_node_to_degree, is_use_unreachable_vertex_heuristics=True)
                path = path[:-1] + extension # extension will start with path[-1]
            else:
                return path

        if g.hasEdge(path[0], path[-1]):
            path.append(path[0])
            return path

        if map_node_to_degree[path[0]] < map_node_to_degree[path[-1]]:
            path = _invert_path(path)

        rotational_options = _rotational_options(g, path)
        for option in rotational_options:
            if g.hasEdge(option[0], option[-1]):
                option.append(option[0])
                return option
        return path


class AntInspiredHeuristics(HamiltonSolver):
    def solve_graphs(self, graphs):
        return [self._solve(graph.num_nodes, graph.edge_index) for graph in graphs]

    def _solve(self, num_nodes, edge_index):
        g = _to_networkit(num_nodes, edge_index)
        max_steps = int(5 * numpy.log(num_nodes) * num_nodes**2)
        mu = [0 for _ in range(g.numberOfNodes())]
        tau = [0 for _ in range(g.numberOfNodes())]
        solution = deque()
        current= 0
        solution.append(current)

        for step in range(1, max_steps + 1):
            neighbors = [(n, mu[n], tau[n]) for n in g.iterNeighbors(current)]
            neighbors.sort(key=lambda n: (n[1], n[2]))
            if len(neighbors) == 0:
                break
            next_node = neighbors[0][0]
            mu[current] = mu[next_node] + 1
            tau[current] = step
            current = next_node
            solution.append(current)
            if len(solution) > num_nodes:
                solution.popleft()
        if solution[0] in [n for n in g.iterNeighbors(solution[-1])]:
            solution.append(solution[0])
        return solution


def load_graph_from_hcp_file(hcp_path):
    lines = Path(hcp_path).read_text().split("\n")
    _dim_line = next(l for l in lines if l.startswith("DIMENSION"))
    num_nodes = int(_dim_line.split()[-1])
    edges_start, edges_end = None, None
    for i in range(len(lines)):
        if lines[i].startswith("EDGE_DATA_SECTION"):
            edges_start = i + 1
        if lines[i].startswith("-1"):
            edges_end = i
    edges_lines = lines[edges_start: edges_end]
    edge_index = torch.tensor([[int(node) for node in l.split()] for l in edges_lines]).t()
    # .hcp start indexing nodes for 1 insetad of 0
    edge_index -= 1
    edge_index = torch.cat([edge_index, edge_index.flip(0)], dim=-1)
    return num_nodes, edge_index
