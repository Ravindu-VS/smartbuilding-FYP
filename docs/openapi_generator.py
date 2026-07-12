"""
OpenAPI Specification Generator

Generates OpenAPI 3.0 spec for the Smart Building ML API.
Used for documentation and dashboards like Swagger UI.
"""

import json
from typing import Dict, Any


def generate_openapi_spec() -> Dict[str, Any]:
    """Generate OpenAPI 3.0 specification."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Smart Building Digital Twin API",
            "description": "Real-time ML-powered occupancy detection and energy management",
            "version": "2.2.0",
            "contact": {
                "name": "Smart Building Team",
            },
        },
        "servers": [
            {
                "url": "http://127.0.0.1:8001",
                "description": "Development server",
            }
        ],
        "paths": {
            "/health": {
                "get": {
                    "summary": "Health check",
                    "tags": ["System"],
                    "responses": {
                        "200": {
                            "description": "System is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "model_loaded": {"type": "boolean"},
                                            "simulation_active": {"type": "boolean"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/system/live": {
                "get": {
                    "summary": "Get current state of all rooms",
                    "tags": ["System"],
                    "responses": {
                        "200": {
                            "description": "Current system state",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "timestamp": {"type": "string"},
                                            "rooms": {
                                                "type": "array",
                                                "items": {"type": "object"},
                                            },
                                            "system": {"type": "object"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/analytics": {
                "get": {
                    "summary": "Get advanced analytics report",
                    "tags": ["Analytics"],
                    "parameters": [
                        {
                            "name": "room_id",
                            "in": "query",
                            "description": "Optional room ID to filter by",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Analytics report",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "occupancy_accuracy": {"type": "object"},
                                            "energy_analysis": {"type": "object"},
                                            "anomalies": {"type": "array"},
                                        },
                                    }
                                }
                            },
                        },
                        "503": {"description": "Service unavailable"},
                    },
                }
            },
            "/api/metrics": {
                "get": {
                    "summary": "Get system performance metrics",
                    "tags": ["Metrics"],
                    "responses": {
                        "200": {
                            "description": "Performance metrics",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "summary": {"type": "object"},
                                            "health": {"type": "object"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/anomalies": {
                "get": {
                    "summary": "Get detected system anomalies",
                    "tags": ["Analytics"],
                    "responses": {
                        "200": {
                            "description": "Anomalies list",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "count": {"type": "integer"},
                                            "anomalies": {"type": "array"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/data/export": {
                "post": {
                    "summary": "Export historical data",
                    "tags": ["Data"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["occupancy", "energy", "full"],
                                        },
                                        "room_id": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Data exported as CSV"},
                        "503": {"description": "Service unavailable"},
                    },
                }
            },
            "/api/rooms/current-state": {
                "get": {
                    "summary": "Get current state of all 4 rooms",
                    "tags": ["Rooms"],
                    "responses": {
                        "200": {
                            "description": "All rooms with full state",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "rooms": {"type": "array"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/rooms/history": {
                "get": {
                    "summary": "Get room history buffers",
                    "tags": ["Rooms"],
                    "parameters": [
                        {
                            "name": "room_id",
                            "in": "query",
                            "description": "Optional room ID",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {"description": "Room history data"}
                    },
                }
            },
            "/api/system/summary": {
                "get": {
                    "summary": "Get building-wide summary",
                    "tags": ["System"],
                    "responses": {
                        "200": {
                            "description": "System summary",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "total_rooms": {"type": "integer"},
                                            "occupied_rooms": {"type": "integer"},
                                            "total_power_watts": {"type": "number"},
                                            "total_cumulative_energy_wh": {"type": "number"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            } ,
            "/predict-occupancy": {
                "post": {
                    "summary": "Predict occupancy from sensor data",
                    "tags": ["Inference"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "Temperature": {"type": "number"},
                                        "Humidity": {"type": "number"},
                                        "Light": {"type": "number"},
                                        "CO2": {"type": "number"},
                                        "HumidityRatio": {"type": "number"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Occupancy prediction"
                        }
                    },
                }
            },
            "/control-decision": {
                "post": {
                    "summary": "Get building control decision",
                    "tags": ["Control"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "Temperature": {"type": "number"},
                                        "Humidity": {"type": "number"},
                                        "Light": {"type": "number"},
                                        "CO2": {"type": "number"},
                                        "HumidityRatio": {"type": "number"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Control decision with mode, light, HVAC"
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Room": {
                    "type": "object",
                    "properties": {
                        "room_id": {"type": "string"},
                        "room_type": {"type": "string"},
                        "sensors": {"type": "object"},
                        "ai": {
                            "type": "object",
                            "properties": {
                                "occupancy_probability": {"type": "number"},
                                "predicted_occupancy": {"type": "integer"},
                                "confidence": {"type": "number"},
                            },
                        },
                        "control": {
                            "type": "object",
                            "properties": {
                                "control_mode": {"type": "string"},
                                "light_action": {"type": "string"},
                                "hvac_action": {"type": "string"},
                            },
                        },
                        "energy": {
                            "type": "object",
                            "properties": {
                                "estimated_power_watts": {"type": "number"},
                                "cumulative_energy_wh": {"type": "number"},
                            },
                        },
                    },
                }
            }
        },
        "tags": [
            {"name": "System", "description": "System status and overview"},
            {"name": "Inference", "description": "ML occupancy prediction"},
            {"name": "Control", "description": "Building control decisions"},
            {"name": "Rooms", "description": "Room-specific state"},
            {"name": "Analytics", "description": "Advanced analytics and reporting"},
            {"name": "Metrics", "description": "System performance metrics"},
            {"name": "Data", "description": "Data export and analysis"},
        ],
    }


if __name__ == "__main__":
    import json
    spec = generate_openapi_spec()
    print(json.dumps(spec, indent=2))
