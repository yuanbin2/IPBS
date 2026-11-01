"""I-007 checks of the small graph and its model-free business rules."""

from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from agent.agent_types import SourceCitation
from agent.rag_tools import grade_source_relevance
from agent.simple_agent import SimpleToolCallingAgent
from agent.tools import ToolResult


class GraphArchitectureTests(SimpleTestCase):
    def test_relevance_rule_is_independent_of_graph_and_shared_by_fallback(self):
        low = SourceCitation(1, "low", 1, 0, 0.119, "low")
        edge = SourceCitation(2, "edge", 2, 0, 0.12, "edge")
        self.assertEqual(grade_source_relevance([low], 0.12), (0.119, []))
        self.assertEqual(grade_source_relevance([low, edge], 0.12), (0.12, [low, edge]))
        self.assertEqual(grade_source_relevance([], 0.12), (0.0, []))

    @patch.dict("os.environ", {"OPENAI_API_KEY": "", "LANGCHAIN_TRACING_V2": "false"})
    def test_graph_has_no_trace_only_citation_node_and_retains_sources(self):
        agent = SimpleToolCallingAgent(Path("."))
        nodes = agent.graph.get_graph().nodes
        self.assertEqual(
            set(nodes) - {"__start__", "__end__"},
            {"query_analyzer", "retrieve", "grade_documents", "rewrite_query", "generate"},
        )
        source = SourceCitation(1, "document", 1, 0, 0.8, "source content")
        with patch(
            "agent.rag_tools.search_sources",
            return_value=(ToolResult("knowledge_search", "query", "source content"), [source]),
        ) as search:
            response = agent.chat("检索我的文档")
        search.assert_called_once()
        self.assertEqual(response.sources, [source])
        self.assertIn("generate -> 1 retained sources", response.trace)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "", "LANGCHAIN_TRACING_V2": "false"})
    def test_low_relevance_rewrites_at_most_once_and_does_not_cite_it(self):
        agent = SimpleToolCallingAgent(Path("."))
        weak = SourceCitation(1, "weak", 1, 0, 0.01, "unrelated")
        with patch(
            "agent.rag_tools.search_sources",
            return_value=(ToolResult("knowledge_search", "query", "unrelated"), [weak]),
        ) as search:
            response = agent.chat("检索我的文档")
        self.assertEqual(search.call_count, 2)
        self.assertEqual(response.sources, [])
        self.assertIn("generate -> no explicit source", response.trace)
