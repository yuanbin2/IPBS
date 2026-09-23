"""Domain-oriented DRF view exports.

Import views from their domain module in new code (e.g.
``from .blog import BlogArticleListCreateView``). These explicit exports
preserve the existing public import path while the application stays
decomposed by domain; star exports are intentionally avoided.
"""

from .agent import (
    AgentChatStreamView,
    AgentChatView,
    ConversationDetailView,
    ConversationListView,
    EvaluationCaseListView,
    EvaluationRunView,
    ObservabilityDashboardView,
)
from .auth import (
    AuthLoginView,
    AuthMeView,
    AuthRegisterView,
    SecurityAuditListView,
    SecurityStatusView,
)
from .blog import (
    BlogAboutView,
    BlogAgentChatView,
    BlogArchiveView,
    BlogArticleDetailView,
    BlogArticleListCreateView,
    BlogArticlePublishView,
    BlogArticleRelatedView,
    BlogCategoryListView,
    BlogCommentCreateView,
    BlogImageUploadView,
    BlogTagListView,
    BlogWritingAgentView,
)
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
