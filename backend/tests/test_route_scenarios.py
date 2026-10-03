import unittest

import networkx as nx

from backend.engine.route_recommender import RouteRecommender
from backend.engine.scenario_manager import ScenarioManager


class FixedPredictor:
    is_trained = True

    def predict_worst_case_delay(self, **kwargs):
        return {"final_delay_presented": 5, "calibration_reason": "Test p85"}


class FixedResolver:
    def resolve_node_to_entry_point(self, location):
        return {"id": location}


def build_recommender(edges):
    recommender = RouteRecommender.__new__(RouteRecommender)
    recommender.unified_graph = nx.DiGraph()
    recommender.unified_graph.add_edges_from(edges)
    recommender.predictor = FixedPredictor()
    recommender.scenario_mgr = ScenarioManager()
    recommender.resolver = FixedResolver()
    return recommender


def transit_edge(mode, baseline_time, cost=0):
    return {
        "transport_mode": mode,
        "type": "transit",
        "baseline_time": baseline_time,
        "cost": cost,
        "base_threat": 0.1,
    }


def route_nodes(mode):
    return [
        (f"SRC:{mode}", {"physical_id": "SRC", "display_name": "Source"}),
        (f"CHOKE-SUEZ:{mode}", {"physical_id": "CHOKE-SUEZ", "display_name": "Suez Canal"}),
        (f"DST:{mode}", {"physical_id": "DST", "display_name": "Destination"}),
    ]


class RouteScenarioTests(unittest.TestCase):
    def test_suez_eta_cost_and_audit_breakdowns_reconcile(self):
        recommender = build_recommender([
            ("SRC:sea", "CHOKE-SUEZ:sea", transit_edge("sea", 10, 100)),
            ("CHOKE-SUEZ:sea", "DST:sea", transit_edge("sea", 10, 200)),
        ])
        recommender.unified_graph.add_nodes_from(route_nodes("sea"))

        result = recommender.recommend("SRC:sea", "DST:sea", scenario="SUEZ_BLOCK")
        route = result["recommendations"][0]

        self.assertEqual(route["adjusted_eta"], 270)
        self.assertEqual(route["audit_trace"]["eta"], {
            "transit": 30,
            "transfer": 0,
            "scenario": 240,
        })
        self.assertEqual(route["total_cost"], 310)
        self.assertEqual(route["audit_trace"]["cost"], {
            "transit": 300,
            "transfer": 0,
            "scenario": 10,
        })
        self.assertAlmostEqual(
            route["adjusted_eta"],
            sum(route["audit_trace"]["eta"].values()),
        )
        self.assertAlmostEqual(
            route["total_cost"],
            sum(route["audit_trace"]["cost"].values()),
        )
        self.assertEqual(route["audit_trace"]["risk"]["baseline"], 0.1)
        self.assertEqual(route["audit_trace"]["risk"]["scenario"], 1.0)

    def test_suez_scenario_reroutes_when_bypass_is_faster(self):
        recommender = build_recommender([
            ("SRC:sea", "CHOKE-SUEZ:sea", transit_edge("sea", 10)),
            ("CHOKE-SUEZ:sea", "DST:sea", transit_edge("sea", 10)),
            ("SRC:sea", "CAPE:sea", transit_edge("sea", 100)),
            ("CAPE:sea", "DST:sea", transit_edge("sea", 100)),
        ])
        recommender.unified_graph.add_nodes_from(route_nodes("sea"))
        recommender.unified_graph.add_node(
            "CAPE:sea", physical_id="CAPE", display_name="Cape of Good Hope"
        )

        result = recommender.recommend("SRC:sea", "DST:sea", scenario="SUEZ_BLOCK")
        route = result["recommendations"][0]

        self.assertEqual(route["adjusted_eta"], 210)
        self.assertNotIn("CHOKE-SUEZ", [leg["to"] for leg in route["legs"]])
        self.assertEqual(route["audit_trace"]["eta"]["scenario"], 0)

    def test_suez_scenario_does_not_delay_air_edges_at_the_same_node(self):
        recommender = build_recommender([
            ("SRC:air", "CHOKE-SUEZ:air", transit_edge("air", 1)),
            ("CHOKE-SUEZ:air", "DST:air", transit_edge("air", 1)),
        ])
        recommender.unified_graph.add_nodes_from(route_nodes("air"))

        result = recommender.recommend("SRC:air", "DST:air", scenario="SUEZ_BLOCK")
        route = result["recommendations"][0]

        self.assertEqual(route["adjusted_eta"], 12)
        self.assertEqual(route["audit_trace"]["eta"]["scenario"], 0)
        self.assertEqual(route["threat_level"], 0.1)


if __name__ == "__main__":
    unittest.main()
