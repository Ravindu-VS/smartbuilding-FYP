"""
AI Assistant Service — RAG Building Knowledge Assistant.
Wraps the existing BuildingAssistant with document retrieval support.
"""
import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class AssistantService:
    """
    RAG-powered Building Knowledge Assistant.
    Loads building manuals, energy policies, and maintenance documents
    as context for the LLM or offline keyword-matching engine.
    """

    def __init__(self, state_manager=None, db_persistence=None,
                 knowledge_path: str = None):
        self.state_manager = state_manager
        self.db = db_persistence
        self.knowledge_path = knowledge_path or os.path.join(PROJECT_ROOT, "docs", "knowledge")
        self._assistant = None
        self._knowledge_base = []
        self._load_assistant()
        self._load_knowledge_documents()

    def _load_assistant(self):
        """Initialize the underlying BuildingAssistant."""
        try:
            from ai.assistant.llm_engine import BuildingAssistant
            self._assistant = BuildingAssistant(
                state_manager=self.state_manager,
                database=self.db
            )
            logger.info("✓ Building Assistant initialized")
        except Exception as e:
            logger.warning(f"Building Assistant init failed: {e}")

    def _load_knowledge_documents(self):
        """
        Load documents from knowledge directory for RAG context.
        Supports .txt and .md files.
        """
        self._knowledge_base = []

        if not os.path.exists(self.knowledge_path):
            # Create the knowledge directory with default documents
            os.makedirs(self.knowledge_path, exist_ok=True)
            self._create_default_documents()

        for filename in os.listdir(self.knowledge_path):
            if filename.endswith((".txt", ".md")):
                filepath = os.path.join(self.knowledge_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    self._knowledge_base.append({
                        "filename": filename,
                        "content": content,
                        "type": "policy" if "policy" in filename.lower() else
                                "manual" if "manual" in filename.lower() else "document",
                    })
                except Exception as e:
                    logger.debug(f"Could not load {filename}: {e}")

        logger.info(f"✓ Loaded {len(self._knowledge_base)} knowledge documents")

    def _create_default_documents(self):
        """Create default knowledge documents for the building."""
        docs = {
            "energy_policy.md": """# Smart Building Energy Policy

## Operational Hours
- Standard operating hours: 08:00 - 18:00 (Monday-Friday)
- HVAC setback mode activates outside operating hours
- Lighting reduces to 10% in unoccupied zones

## Temperature Standards
- Occupied zones: 22°C - 24°C (ISO 7730 PMV ±0.5)
- Unoccupied zones: 18°C (heating) / 26°C (cooling)
- Server rooms: 20°C - 22°C (constant)

## Energy Targets
- Annual energy reduction target: 25% compared to baseline
- Peak demand shaving during 14:00 - 17:00
- Renewable energy integration priority

## Comfort Priority
- PMV index must remain within ±0.5 during occupied hours
- Minimum illumination: 300 lux for office work
- CO₂ levels must remain below 1000 ppm
""",
            "hvac_manual.md": """# HVAC System Manual

## System Overview
- Central air handling unit with variable air volume (VAV) boxes
- Individual zone temperature control via motorized dampers
- Heat recovery ventilation for fresh air

## Operating Modes
1. **AUTO**: AI-controlled optimization (default)
2. **ECO**: Energy-saving mode (wider comfort band)
3. **BOOST**: Maximum cooling/heating for rapid response
4. **OFF**: System shutdown (maintenance only)

## Maintenance Schedule
- Filter replacement: Every 3 months
- Coil cleaning: Every 6 months
- Full system inspection: Annually
- Refrigerant check: Every 2 years

## Fault Codes
- E001: Compressor overtemperature
- E002: Fan motor failure
- E003: Refrigerant pressure low
- E004: Thermostat communication lost
- E005: Damper actuator stuck
""",
            "maintenance_procedures.md": """# Building Maintenance Procedures

## Daily Checks
- Verify all sensor nodes are reporting (check dashboard)
- Review overnight energy consumption patterns
- Check for anomaly alerts in the AI system

## Weekly Tasks
- Review energy savings reports
- Calibrate temperature sensors showing drift > 0.5°C
- Test emergency lighting systems

## Monthly Tasks
- Export energy consumption data for reporting
- Review and update occupancy schedules
- Test backup power systems
- Update AI model if new training data available

## Emergency Procedures
- Power outage: UPS activates, critical systems only
- HVAC failure: Open windows, deploy portable units
- Sensor failure: System falls back to schedule-based control
""",
        }

        for filename, content in docs.items():
            filepath = os.path.join(self.knowledge_path, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

    def query(self, message: str) -> Dict[str, Any]:
        """
        Process a user query with RAG context augmentation.

        Args:
            message: User's natural language question

        Returns:
            Dict with response text, context used, and LLM type
        """
        # Build enhanced context with knowledge documents
        knowledge_context = self._retrieve_relevant_docs(message)

        if self._assistant:
            # Inject knowledge into the assistant's context
            result = self._assistant.generate_response(message)

            # Augment with relevant knowledge documents
            if knowledge_context:
                result["knowledge_sources"] = [
                    doc["filename"] for doc in knowledge_context
                ]
            return result

        # Fallback: simple keyword matching against knowledge base
        return self._offline_query(message, knowledge_context)

    def _retrieve_relevant_docs(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Simple keyword-based retrieval from the knowledge base.
        Returns the most relevant documents based on keyword overlap.
        """
        query_words = set(query.lower().split())
        scored = []

        for doc in self._knowledge_base:
            doc_words = set(doc["content"].lower().split())
            overlap = len(query_words & doc_words)
            if overlap > 0:
                scored.append((overlap, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]

    def _offline_query(self, message: str, context: List[Dict]) -> Dict[str, Any]:
        """Fallback query handler using keyword matching."""
        msg = message.lower()

        if any(w in msg for w in ["policy", "rule", "standard", "regulation"]):
            for doc in context:
                if doc["type"] == "policy":
                    return {
                        "response": f"Based on building energy policy:\n\n{doc['content'][:500]}...",
                        "context_retrieved": {"documents": [doc["filename"]]},
                        "llm_used": "OfflineRAG",
                    }

        if any(w in msg for w in ["maintenance", "repair", "fix", "broken"]):
            for doc in context:
                if "maintenance" in doc["filename"].lower():
                    return {
                        "response": f"Maintenance information:\n\n{doc['content'][:500]}...",
                        "context_retrieved": {"documents": [doc["filename"]]},
                        "llm_used": "OfflineRAG",
                    }

        if any(w in msg for w in ["hvac", "cooling", "heating", "air"]):
            for doc in context:
                if "hvac" in doc["filename"].lower():
                    return {
                        "response": f"HVAC system information:\n\n{doc['content'][:500]}...",
                        "context_retrieved": {"documents": [doc["filename"]]},
                        "llm_used": "OfflineRAG",
                    }

        # Generic response
        return {
            "response": "I can help with energy policies, HVAC operation, and maintenance procedures. "
                       "Please ask about specific building systems or energy management topics.",
            "context_retrieved": {"documents": []},
            "llm_used": "OfflineRAG",
        }

    def get_anomalies(self) -> List[Dict[str, Any]]:
        """
        Get current anomaly detections from the predictive maintenance module.
        """
        anomalies = []

        try:
            from ai.maintenance import PredictiveMaintenance
            pm = PredictiveMaintenance()

            # Check each zone if state manager is available
            if self.state_manager:
                import numpy as np
                zone_names = ["Office", "MeetingRoom", "Corridor"]
                for zone in zone_names:
                    state = self.state_manager.get_zone_state(zone)
                    if state:
                        reading = np.array([
                            state.get("temperature", 22.0),
                            state.get("humidity", 50.0),
                            state.get("co2", 400.0),
                            state.get("illumination", 300.0),
                            state.get("hvac_power", 0.0),
                            state.get("lighting_power", 0.0),
                        ])

                        # Run heuristic checks
                        diagnostics = pm.run_diagnostics(reading)
                        for diag in diagnostics:
                            if diag.get("status") == "warning":
                                anomalies.append({
                                    "room_id": zone,
                                    "anomaly_type": diag.get("check", "unknown"),
                                    "severity": "medium",
                                    "description": diag.get("message", ""),
                                    "detected_at": datetime.now().isoformat(),
                                    "anomaly_score": 0.7,
                                })
        except Exception as e:
            logger.debug(f"Anomaly detection: {e}")

        return anomalies
