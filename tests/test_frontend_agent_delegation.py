"""Unit tests verifying frontend delegates conversations to Customer Agent and Customer Service Agent."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestFrontendAgentDelegation(unittest.TestCase):
    def test_extract_agent_engine_events_parses_text_tools_and_responses(self):
        import frontend.app as frontend_app

        events = [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"function_call": {"name": "check_order_status", "args": {"order_id": "ORD-1001"}}}
                    ],
                }
            },
            {
                "content": {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": "check_order_status",
                                "response": {"result": "Delivered"},
                            }
                        }
                    ],
                }
            },
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": "Your order ORD-1001 was delivered. Please check the cables first."}],
                }
            },
        ]

        text, tools, calls, responses = frontend_app._extract_agent_engine_events(events)
        self.assertEqual(text, "Your order ORD-1001 was delivered. Please check the cables first.")
        self.assertEqual(tools, ["check_order_status"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], {"order_id": "ORD-1001"})
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["name"], "check_order_status")

    def test_execute_service_turn_delegates_to_agent_engine(self):
        import frontend.app as frontend_app

        fake_engine = MagicMock()
        fake_engine.stream_query.return_value = [
            {
                "content": {
                    "parts": [
                        {"function_call": {"name": "lookup_warranty_policy", "args": {"category_or_product": "TV"}}},
                        {"text": "Please power cycle the unit first. We cannot dispatch a technician yet."},
                    ]
                }
            }
        ]

        with patch.object(frontend_app, "CUSTOMER_SERVICE_AGENT_ID", "2556039354015285248"), \
             patch.object(frontend_app, "_get_agent_engine", return_value=fake_engine):
            text, tools = frontend_app._execute_service_turn(
                adk_session_id="sess-123",
                adk_user_id="cust_999",
                last_customer_text="My TV has audio dropouts.",
                persona={"product": "LG OLED TV"},
                history=[],
            )

        fake_engine.stream_query.assert_called_once_with(
            user_id="cust_999",
            session_id="sess-123",
            message="My TV has audio dropouts.",
        )
        self.assertIn("power cycle", text)
        self.assertEqual(tools, ["lookup_warranty_policy"])

    def test_initiate_customer_persona_delegates_to_customer_agent_engine(self):
        import frontend.app as frontend_app

        fake_persona = {
            "customer_id": 424242,
            "customer_name": "Elena Rostova",
            "category": "Hardware Malfunction",
            "product": "LG C4 OLED TV",
            "order_id": "ORD-1001",
            "opening": "My TV audio keeps cutting out.",
            "patience": "Moderate",
        }
        fake_engine = MagicMock()
        fake_engine.stream_query.return_value = [
            {
                "content": {
                    "parts": [
                        {
                            "function_response": {
                                "name": "generate_customer_persona",
                                "response": fake_persona,
                            }
                        }
                    ]
                }
            },
            {
                "content": {
                    "parts": [{"text": "My TV audio keeps cutting out."}]
                }
            },
        ]

        with patch.object(frontend_app, "CUSTOMER_AGENT_ID", "8810413336526061568"), \
             patch.object(frontend_app, "_get_agent_engine", return_value=fake_engine):
            persona = frontend_app._initiate_customer_persona_via_agent("cust-sess-1", "cust_424242")

        fake_engine.stream_query.assert_called_once()
        self.assertEqual(persona["customer_name"], "Elena Rostova")
        self.assertEqual(persona["order_id"], "ORD-1001")

    def test_evaluate_and_persist_rating_delegates_to_customer_agent_engine(self):
        import frontend.app as frontend_app

        fake_engine = MagicMock()
        fake_engine.stream_query.return_value = [
            {
                "content": {
                    "parts": [
                        {
                            "function_call": {
                                "name": "write_customer_rating_to_bigquery",
                                "args": {
                                    "customer_id": 424242,
                                    "customer_name": "Elena Rostova",
                                    "rating": 2,
                                    "description": "Too many diagnostic hoops.",
                                },
                            }
                        }
                    ]
                }
            },
            {
                "content": {
                    "parts": [
                        {
                            "function_response": {
                                "name": "write_customer_rating_to_bigquery",
                                "response": {
                                    "status": "success",
                                    "row": {
                                        "rating": 2,
                                        "description": "Too many diagnostic hoops.",
                                    },
                                },
                            }
                        }
                    ]
                }
            },
        ]

        with patch.object(frontend_app, "CUSTOMER_AGENT_ID", "8810413336526061568"), \
             patch.object(frontend_app, "_get_agent_engine", return_value=fake_engine):
            rating, desc, persisted = frontend_app._evaluate_and_persist_customer_rating(
                cust_session_id="cust-sess-1",
                cust_user_id="cust_424242",
                persona={"customer_id": 424242, "customer_name": "Elena Rostova"},
                history=[],
                aborted=False,
            )

        self.assertEqual(rating, 2)
        self.assertEqual(desc, "Too many diagnostic hoops.")
        self.assertTrue(persisted)


if __name__ == "__main__":
    unittest.main()
