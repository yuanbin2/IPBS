"""Domain-oriented DRF view exports.

Import views from their domain module in new code (e.g.
``from .blog_articles import BlogArticleListCreateView``). These explicit
exports preserve the existing public import path while the application
stays decomposed by domain; star exports are intentionally avoided.
"""

from .auth import (
    AuthLoginView,
    AuthMeView,
    AuthRegisterView,
    SecurityAuditListView,
    SecurityStatusView,
)
from .blog_agent import BlogAgentChatView
from .blog_articles import (
    BlogArticleDetailView,
    BlogArticleListCreateView,
    BlogArticlePublishView,
    BlogArticleRelatedView,
    BlogImageUploadView,
)
from .blog_public import (
    BlogAboutView,
    BlogArchiveView,
    BlogCategoryListView,
    BlogCommentCreateView,
    BlogTagListView,
)
from .blog_writing import BlogWritingAgentView
from .chat import AgentChatStreamView, AgentChatView
from .conversations import ConversationDetailView, ConversationListView
from .governance import (
    ApprovalRequestDetailView,
    ApprovalRequestListView,
    MCPToolBulkHealthCheckView,
    MCPToolDetailView,
    MCPToolExecuteView,
    MCPToolHealthCheckView,
    MCPToolListView,
)
from .knowledge import (
    DocumentDetailView,
    DocumentListUploadView,
    DocumentReindexView,
    KnowledgeBaseArchiveView,
    KnowledgeBaseDetailView,
    KnowledgeBaseListView,
    KnowledgeSearchView,
    TaskStatusView,
)
from .observability import (
    EvaluationCaseListView,
    EvaluationRunView,
    ObservabilityDashboardView,
)

__all__ = [
    "AgentChatStreamView",
    "AgentChatView",
    "ApprovalRequestDetailView",
    "ApprovalRequestListView",
    "AuthLoginView",
    "AuthMeView",
    "AuthRegisterView",
    "BlogAboutView",
    "BlogAgentChatView",
    "BlogArchiveView",
    "BlogArticleDetailView",
    "BlogArticleListCreateView",
    "BlogArticlePublishView",
    "BlogArticleRelatedView",
    "BlogCategoryListView",
    "BlogCommentCreateView",
    "BlogImageUploadView",
    "BlogTagListView",
    "BlogWritingAgentView",
    "ConversationDetailView",
    "ConversationListView",
    "DocumentDetailView",
    "DocumentListUploadView",
    "DocumentReindexView",
    "EvaluationCaseListView",
    "EvaluationRunView",
    "KnowledgeBaseArchiveView",
    "KnowledgeBaseDetailView",
    "KnowledgeBaseListView",
    "KnowledgeSearchView",
    "MCPToolBulkHealthCheckView",
    "MCPToolDetailView",
    "MCPToolExecuteView",
    "MCPToolHealthCheckView",
    "MCPToolListView",
    "ObservabilityDashboardView",
    "SecurityAuditListView",
    "SecurityStatusView",
    "TaskStatusView",
]
