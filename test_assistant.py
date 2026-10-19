import unittest
import json
import os
import sys

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ai.assistant.llm_engine import BuildingAssistant
from smart_building_api_flask import app

class TestAssistant(unittest.TestCase):
    
    def test_rag_context_retrieval(self):
        print("Testing RAG Context Retrieval...")
        assistant = BuildingAssistant()
        context = assistant.retrieve_context()
        
        self.assertIn("timestamp", context)
        self.assertIn("energy_summary", context)
        self.assertIn("zones", context)
        self.assertIn("Office", context["zones"])
        self.assertIn("MeetingRoom", context["zones"])
        self.assertIn("Corridor", context["zones"])
        
        # Verify properties are populated
        self.assertTrue(hasattr(context["zones"]["Office"], "get") or isinstance(context["zones"]["Office"], dict))
        self.assertIn("temperature", context["zones"]["Office"])

    def test_offline_response_solver(self):
        print("Testing Offline RAG Solver Responses...")
        assistant = BuildingAssistant()
        
        # Test energy query
        res_energy = assistant.generate_response("How much energy did we save today?")
        self.assertIn("response", res_energy)
        self.assertIn("energy_summary", res_energy["context_retrieved"])
        self.assertIn("PPO", res_energy["response"])
        
        # Test comfort query
        res_comfort = assistant.generate_response("Is the meeting room temperature comfortable?")
        self.assertIn("Office", res_comfort["response"])
        
        # Test anomaly query
        res_anomaly = assistant.generate_response("Are there any active maintenance faults?")
        self.assertIn("optimal efficiency", res_anomaly["response"])
        
        # Test status summary report query
        res_status = assistant.generate_response("Give me a general status report.")
        self.assertIn("Status Report", res_status["response"])

    def test_flask_assistant_route(self):
        print("Testing Flask Assistant Route /api/v1/assistant...")
        client = app.test_client()
        
        # Test valid POST request
        payload = {"message": "Give me a summary of current savings."}
        response = client.post(
            "/api/v1/assistant",
            data=json.dumps(payload),
            content_type="application/json"
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("response", data)
        self.assertIn("context_retrieved", data)
        self.assertIn("llm_used", data)
        self.assertEqual(data["llm_used"], "OfflineRAGTemplate")
        
        # Test invalid request (missing message)
        bad_payload = {}
        bad_response = client.post(
            "/api/v1/assistant",
            data=json.dumps(bad_payload),
            content_type="application/json"
        )
        self.assertEqual(bad_response.status_code, 400)

if __name__ == "__main__":
    unittest.main()
