"""Domain serializers and serialization helpers.

Import explicitly from this package (e.g. ``from ..serializers import serialize_article``).
Star exports are intentionally avoided so the public surface stays traceable.
"""

from .agent import (
    AgentObservationSerializer,
    ConversationProjectSerializer,
    ConversationSerializer,
    MessageSerializer,
    serialize_agent_observation,
    serialize_conversation,
    serialize_message,
    serialize_project,
)
from .auth import (
    SecurityAuditEventSerializer,
    UserProfileSerializer,
    serialize_security_audit_event,
    serialize_user_profile,
)
from .blog import (
    ArticleCategorySerializer,
    ArticleTagSerializer,
    BlogAgentMessageSerializer,
    BlogArticleSerializer,
    BlogCommentSerializer,
    serialize_article,
    serialize_blog_agent_message,
    serialize_category,
    serialize_tag,
)
from .evaluation import (
    EvaluationCaseSerializer,
    EvaluationRunSerializer,
    serialize_evaluation_case,
    serialize_evaluation_run,
)
from .governance import (
    ApprovalRequestSerializer,
    MCPToolSerializer,
    serialize_approval_request,
    serialize_mcp_tool,
)
from .knowledge import (
    DocumentSerializer,
    KnowledgeBaseSerializer,
    serialize_document,
    serialize_knowledge_base,
)

__all__ = [
    "AgentObservationSerializer",
    "ConversationProjectSerializer",
    "ApprovalRequestSerializer",
    "ArticleCategorySerializer",
    "ArticleTagSerializer",
    "BlogAgentMessageSerializer",
    "BlogArticleSerializer",
    "BlogCommentSerializer",
    "ConversationSerializer",
    "DocumentSerializer",
    "EvaluationCaseSerializer",
    "EvaluationRunSerializer",
    "KnowledgeBaseSerializer",
    "MCPToolSerializer",
    "MessageSerializer",
    "SecurityAuditEventSerializer",
    "UserProfileSerializer",
    "serialize_agent_observation",
    "serialize_approval_request",
    "serialize_article",
    "serialize_blog_agent_message",
    "serialize_category",
    "serialize_conversation",
    "serialize_project",
    "serialize_document",
    "serialize_evaluation_case",
    "serialize_evaluation_run",
    "serialize_knowledge_base",
    "serialize_mcp_tool",
    "serialize_message",
    "serialize_security_audit_event",
    "serialize_tag",
    "serialize_user_profile",
]
