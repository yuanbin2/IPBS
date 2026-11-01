"""Production-role, JWT, and workspace boundaries exercised through HTTP and JWT login."""

import base64
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import (
    ApprovalRequest,
    BlogArticle,
    Conversation,
    Document,
    KnowledgeBase,
    MCPTool,
    SecurityAuditEvent,
    UserProfile,
)
from .support import NO_MODEL_ENV, SecurityTransportTestCase

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGNUrrjDwMDAxAAGABEFAXsZWVM7AAAAAElFTkSuQmCC"
)


@override_settings(AGENT_SECURITY_ENFORCED=True)
class SecurityRoleMatrixTests(SecurityTransportTestCase):
    password = "matrix-test-password-2026"

    def login_as(self, role, workspace="default", username=None):
        username = username or f"matrix-{role}-{UserProfile.objects.count()}"
        user = get_user_model().objects.create_user(username=username, password=self.password)
        UserProfile.objects.create(user=user, role=role, workspace_key=workspace)
        response = self.client.post(
            "/api/agent/auth/login/",
            {"username": username, "password": self.password},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["token"]
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return user, token

    def clear_identity(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION", None)

    def image_upload(self):
        return SimpleUploadedFile("role-test.png", TINY_PNG, content_type="image/png")

    def document_upload(self):
        return SimpleUploadedFile("role-test.txt", b"Access-controlled document.", content_type="text/plain")

    def test_public_registration_ignores_privileged_role_and_workspace_claims(self):
        for index, role in enumerate(("admin", "operator")):
            username = f"registration-escalation-{index}"
            response = self.client.post(
                "/api/agent/auth/register/",
                {
                    "username": username,
                    "password": self.password,
                    "role": role,
                    "workspace_key": "attacker-selected-workspace",
                },
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 201)
            registered = response.json()
            self.assertEqual(registered["user"]["role"], UserProfile.Role.VISITOR)
            self.assertEqual(registered["user"]["workspace_key"], "default")
            self.assertFalse(get_user_model().objects.get(username=username).is_staff)
            status_response = self.client.get(
                "/api/agent/security/status/",
                HTTP_AUTHORIZATION=f"Bearer {registered['token']}",
                HTTP_HOST="localhost",
            )
            self.assertEqual(status_response.status_code, 403)

    def test_invalid_expired_and_forged_jwt_do_not_grant_admin_access(self):
        user = get_user_model().objects.create_user(username="jwt-matrix-user", password=self.password)
        UserProfile.objects.create(user=user, role=UserProfile.Role.ADMIN, workspace_key="default")
        expired = RefreshToken.for_user(user).access_token
        expired.set_exp(lifetime=timedelta(seconds=-1))
        candidates = ["not-a-jwt", str(expired), "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9."]

        for token in candidates:
            with self.subTest(token=token[:12]):
                response = self.client.get(
                    "/api/agent/security/status/",
                    HTTP_AUTHORIZATION=f"Bearer {token}",
                    HTTP_X_ROLE="admin",
                    HTTP_X_WORKSPACE="default",
                    HTTP_HOST="localhost",
                )
                self.assertEqual(response.status_code, 403)

    def test_only_operator_and_admin_can_upload_public_images_and_knowledge_documents(self):
        self.clear_identity()
        anonymous_image = self.client.post(
            "/api/agent/blog/images/", {"image": self.image_upload()}, HTTP_HOST="localhost"
        )
        anonymous_document = self.client.post(
            "/api/agent/documents/", {"file": self.document_upload()}, HTTP_HOST="localhost"
        )
        self.assertEqual(anonymous_image.status_code, 403)
        self.assertEqual(anonymous_document.status_code, 403)

        self.login_as(UserProfile.Role.VISITOR)
        visitor_image = self.client.post(
            "/api/agent/blog/images/", {"image": self.image_upload()}, HTTP_HOST="localhost"
        )
        visitor_document = self.client.post(
            "/api/agent/documents/", {"file": self.document_upload()}, HTTP_HOST="localhost"
        )
        self.assertEqual(visitor_image.status_code, 403)
        self.assertEqual(visitor_document.status_code, 403)

        self.login_as(UserProfile.Role.OPERATOR)
        operator_image = self.client.post(
            "/api/agent/blog/images/", {"image": self.image_upload()}, HTTP_HOST="localhost"
        )
        operator_document = self.client.post(
            "/api/agent/documents/", {"file": self.document_upload()}, HTTP_HOST="localhost"
        )
        self.assertEqual(operator_image.status_code, 201)
        self.assertEqual(operator_document.status_code, 202)
        self.assertEqual(operator_document.json()["ingestion_job"]["status"], "pending")
        self.assertTrue(operator_document.json()["task_url"].endswith(operator_document.json()["task_id"] + "/"))

        self.login_as(UserProfile.Role.ADMIN)
        admin_image = self.client.post("/api/agent/blog/images/", {"image": self.image_upload()}, HTTP_HOST="localhost")
        admin_document = self.client.post(
            "/api/agent/documents/", {"file": self.document_upload()}, HTTP_HOST="localhost"
        )
        self.assertEqual(admin_image.status_code, 201)
        self.assertEqual(admin_document.status_code, 202)

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_private_agent_chat_requires_operator_but_blog_visitor_chat_stays_public(self):
        self.clear_identity()
        for endpoint in ("/api/agent/chat/", "/api/agent/chat/stream/"):
            response = self.client.post(
                endpoint,
                {"message": "tell me about uploaded documents"},
                content_type="application/json",
                HTTP_HOST="localhost",
            )
            self.assertEqual(response.status_code, 403)
        self.assertEqual(Conversation.objects.count(), 0)

        self.login_as(UserProfile.Role.VISITOR)
        visitor_chat = self.client.post(
            "/api/agent/chat/",
            {"message": "tell me about uploaded documents"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(visitor_chat.status_code, 403)

        public_blog_chat = self.client.post(
            "/api/agent/blog/agent/chat/",
            {"message": "这个项目使用了什么技术栈？", "session_key": "security-matrix-public"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(public_blog_chat.status_code, 200)

        self.login_as(UserProfile.Role.OPERATOR)
        operator_chat = self.client.post(
            "/api/agent/chat/",
            {"message": "what is 2 + 2?"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(operator_chat.status_code, 200)

    def test_article_publish_requires_admin_and_is_workspace_scoped(self):
        self.login_as(UserProfile.Role.OPERATOR, username="article-author")
        created = self.client.post(
            "/api/agent/blog/articles/",
            {"title": "Approval matrix article", "content": "Private until approved."},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(created.status_code, 202)
        approval_id = created.json()["approval"]["id"]
        article_slug = created.json()["article"]["slug"]

        denied = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(denied.status_code, 403)

        self.login_as(UserProfile.Role.ADMIN, workspace="other-workspace")
        foreign = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(ApprovalRequest.objects.get(pk=approval_id).status, ApprovalRequest.Status.PENDING)

        self.login_as(UserProfile.Role.ADMIN, workspace="default")
        approved = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(BlogArticle.objects.get(slug=article_slug).status, BlogArticle.Status.PUBLISHED)

    def test_workspace_token_scopes_reads_and_ignores_workspace_header_spoofing(self):
        alpha_base = KnowledgeBase.objects.create(name="alpha-private", workspace_key="alpha")
        alpha_document = Document.objects.create(
            knowledge_base=alpha_base,
            title="alpha private document",
            workspace_key="alpha",
            status=Document.Status.READY,
        )
        draft = BlogArticle.objects.create(
            title="alpha private draft",
            slug="alpha-private-draft",
            workspace_key="alpha",
            author_name="alpha-author",
            content="private draft body",
            status=BlogArticle.Status.DRAFT,
        )

        self.clear_identity()
        anonymous_bases = self.client.get("/api/agent/knowledge-bases/", HTTP_X_WORKSPACE="alpha")
        anonymous_docs = self.client.get(
            f"/api/agent/documents/?knowledge_base_id={alpha_base.pk}", HTTP_X_WORKSPACE="alpha"
        )
        anonymous_search = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "private", "knowledge_base_id": alpha_base.pk},
            content_type="application/json",
            HTTP_X_WORKSPACE="alpha",
        )
        self.assertEqual(anonymous_bases.status_code, 403)
        self.assertEqual(anonymous_docs.status_code, 403)
        self.assertEqual(anonymous_search.status_code, 403)
        anonymous_draft = self.client.get(f"/api/agent/blog/articles/{draft.slug}/", HTTP_X_WORKSPACE="alpha")
        self.assertEqual(anonymous_draft.status_code, 404)

        self.login_as(UserProfile.Role.VISITOR, workspace="beta")
        visitor_bases = self.client.get("/api/agent/knowledge-bases/", HTTP_X_WORKSPACE="alpha")
        visitor_docs = self.client.get(
            f"/api/agent/documents/?knowledge_base_id={alpha_base.pk}", HTTP_X_WORKSPACE="alpha"
        )
        visitor_search = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "private", "knowledge_base_id": alpha_base.pk},
            content_type="application/json",
            HTTP_X_WORKSPACE="alpha",
        )
        self.assertEqual(visitor_bases.status_code, 403)
        self.assertEqual(visitor_docs.status_code, 403)
        self.assertEqual(visitor_search.status_code, 403)

        self.login_as(UserProfile.Role.OPERATOR, workspace="beta")
        docs = self.client.get(
            f"/api/agent/documents/?knowledge_base_id={alpha_base.pk}",
            HTTP_X_WORKSPACE="alpha",
            HTTP_HOST="localhost",
        )
        private_search = self.client.post(
            "/api/agent/knowledge-search/",
            {"query": "alpha private", "knowledge_base_id": alpha_base.pk},
            content_type="application/json",
            HTTP_X_WORKSPACE="alpha",
            HTTP_HOST="localhost",
        )
        hidden_draft = self.client.get(
            f"/api/agent/blog/articles/{draft.slug}/",
            HTTP_X_WORKSPACE="alpha",
            HTTP_HOST="localhost",
        )
        self.assertEqual(docs.status_code, 200)
        self.assertNotIn(alpha_document.title, str(docs.json()))
        self.assertEqual(private_search.status_code, 404)
        self.assertEqual(hidden_draft.status_code, 404)

        forbidden_base = self.client.post(
            "/api/agent/documents/",
            {"file": self.document_upload(), "knowledge_base_id": alpha_base.pk},
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE="alpha",
        )
        self.assertEqual(forbidden_base.status_code, 404)
        self.assertFalse(Document.objects.filter(knowledge_base=alpha_base).exclude(pk=alpha_document.pk).exists())

        created = self.client.post(
            "/api/agent/blog/articles/",
            {"title": "beta workspace article", "content": "Must remain in beta."},
            content_type="application/json",
            HTTP_HOST="localhost",
            HTTP_X_WORKSPACE="alpha",
        )
        self.assertEqual(created.status_code, 202)
        self.assertEqual(BlogArticle.objects.get(slug=created.json()["article"]["slug"]).workspace_key, "beta")
        self.assertEqual(BlogArticle.objects.get(slug=draft.slug).workspace_key, "alpha")

    def test_other_workspace_admin_cannot_read_security_audit_events(self):
        SecurityAuditEvent.objects.create(
            event_type=SecurityAuditEvent.EventType.ACCESS_DENIED,
            actor="alpha-user",
            role=UserProfile.Role.VISITOR,
            workspace_key="alpha",
            path="/api/private/",
            detail="alpha-only audit event",
        )
        self.login_as(UserProfile.Role.OPERATOR, workspace="beta")
        operator_response = self.client.get("/api/agent/security/audit-events/", HTTP_HOST="localhost")
        self.assertEqual(operator_response.status_code, 403)

        self.login_as(UserProfile.Role.ADMIN, workspace="beta")
        admin_response = self.client.get("/api/agent/security/audit-events/", HTTP_HOST="localhost")
        self.assertEqual(admin_response.status_code, 200)
        self.assertNotIn("alpha-only audit event", str(admin_response.json()))

    def test_security_audit_events_are_paged_by_limit_and_offset(self):
        """审计列表支持游标分页（前端滚动到底再取下一页），页面之间不得重叠。"""
        self.login_as(UserProfile.Role.ADMIN, workspace="default")
        base = "/api/agent/security/audit-events/"
        # 登录本身会写一条 audit 事件，先取基线再断言增量。
        baseline = self.client.get(base, HTTP_HOST="localhost").json()["total"]
        for index in range(5):
            SecurityAuditEvent.objects.create(
                event_type=SecurityAuditEvent.EventType.ACCESS_DENIED,
                actor="paging-actor",
                role=UserProfile.Role.VISITOR,
                workspace_key="default",
                path="/api/private/",
                detail=f"paging detail {index}",
            )

        first = self.client.get(f"{base}?limit=2&offset=0", HTTP_HOST="localhost").json()
        self.assertEqual(first["total"], baseline + 5)
        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["has_more"])

        second = self.client.get(f"{base}?limit=2&offset=2", HTTP_HOST="localhost").json()
        first_ids = [item["id"] for item in first["events"]]
        second_ids = [item["id"] for item in second["events"]]
        self.assertTrue(set(first_ids).isdisjoint(second_ids))

        last_page = self.client.get(f"{base}?limit=2&offset={baseline + 4}", HTTP_HOST="localhost").json()
        self.assertEqual(len(last_page["events"]), 1)
        self.assertFalse(last_page["has_more"])

        beyond = self.client.get(f"{base}?limit=2&offset={baseline + 5}", HTTP_HOST="localhost").json()
        self.assertEqual(beyond["events"], [])
        self.assertFalse(beyond["has_more"])

    def test_security_audit_events_reject_malformed_paging_params_softly(self):
        """非法或越界的 limit/offset 退回安全值，而不是 500 或全表返回。"""
        self.login_as(UserProfile.Role.ADMIN, workspace="default")
        base = "/api/agent/security/audit-events/"
        total = self.client.get(base, HTTP_HOST="localhost").json()["total"]

        for query in ("limit=abc&offset=-5", "limit=0", "limit=-3"):
            response = self.client.get(f"{base}?{query}", HTTP_HOST="localhost")
            self.assertEqual(response.status_code, 200, query)
            self.assertEqual(response.json()["total"], total, query)

        clamped = self.client.get(f"{base}?limit=9999", HTTP_HOST="localhost").json()
        self.assertEqual(len(clamped["events"]), min(total, 50))

    def test_admin_revocation_of_web_search_survives_registry_listing(self):
        self.login_as(UserProfile.Role.ADMIN)
        self.client.get("/api/agent/mcp-tools/", HTTP_HOST="localhost")
        tool = MCPTool.objects.get(name="web_search")
        self.assertTrue(tool.is_enabled)
        disabled = self.client.patch(
            f"/api/agent/mcp-tools/{tool.pk}/",
            {"is_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(disabled.status_code, 200)
        self.client.get("/api/agent/mcp-tools/", HTTP_HOST="localhost")
        tool.refresh_from_db()
        self.assertFalse(tool.is_enabled)
        blocked = self.client.post(
            f"/api/agent/mcp-tools/{tool.pk}/execute/",
            {"query": "external page instructions cannot override disabled tool"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(blocked.status_code, 400)

    def test_safe_database_stats_is_scoped_to_authenticated_workspace(self):
        from agent.mcp_tools import LocalMCPToolRunner

        no_context = LocalMCPToolRunner(Path(".")).run("safe_database_stats", "show counts")
        self.assertEqual(no_context.output, "workspace context required")
        alpha = KnowledgeBase.objects.create(name="alpha-stats", workspace_key="alpha")
        beta = KnowledgeBase.objects.create(name="beta-stats", workspace_key="default")
        Document.objects.create(knowledge_base=alpha, workspace_key="alpha", title="private alpha")
        Document.objects.create(knowledge_base=beta, workspace_key="default", title="beta")
        tool = MCPTool.objects.get(name="safe_database_stats")
        self.login_as(UserProfile.Role.OPERATOR)
        response = self.client.post(
            f"/api/agent/mcp-tools/{tool.pk}/execute/",
            {"query": "show counts", "workspace_key": "alpha"},
            content_type="application/json",
            HTTP_X_WORKSPACE="alpha",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("- knowledge_bases: 1", response.json()["output"])
        self.assertIn("- documents: 1", response.json()["output"])

    def test_revoked_role_and_deactivated_user_cannot_reuse_existing_jwt(self):
        user, token = self.login_as(UserProfile.Role.OPERATOR, workspace="alpha")
        self.assertEqual(self.client.get("/api/agent/documents/", HTTP_HOST="localhost").status_code, 200)
        profile = UserProfile.objects.get(user=user)
        profile.role = UserProfile.Role.VISITOR
        profile.save(update_fields=["role"])
        denied = self.client.get(
            "/api/agent/documents/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_ROLE="admin",
            HTTP_X_WORKSPACE="alpha",
            HTTP_HOST="localhost",
        )
        self.assertEqual(denied.status_code, 403)
        user.is_active = False
        user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get("/api/agent/documents/", HTTP_HOST="localhost").status_code, 403)

    def test_foreign_tool_and_approval_ids_do_not_cross_workspace(self):
        tool = MCPTool.objects.get(name="web_search")
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.EXECUTE_MCP_TOOL,
            workspace_key="default",
            title="default workspace tool",
            payload={"tool_id": tool.pk, "tool_name": tool.name, "query": "test"},
        )
        self.login_as(UserProfile.Role.OPERATOR, workspace="other")
        foreign_tool = self.client.post(
            f"/api/agent/mcp-tools/{tool.pk}/execute/",
            {"query": "forged tool id"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(foreign_tool.status_code, 404)
        self.login_as(UserProfile.Role.ADMIN, workspace="other")
        foreign_approval = self.client.post(
            f"/api/agent/approvals/{approval.pk}/",
            {"decision": "approve"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(foreign_approval.status_code, 404)
        self.assertEqual(ApprovalRequest.objects.get(pk=approval.pk).status, ApprovalRequest.Status.PENDING)

    def test_anonymous_cannot_read_legacy_anonymous_conversation(self):
        conversation = Conversation.objects.create(
            title="legacy private history", workspace_key="default", owner_username="anonymous"
        )
        self.clear_identity()
        listing = self.client.get("/api/agent/conversations/", HTTP_HOST="localhost")
        detail = self.client.get(f"/api/agent/conversations/{conversation.pk}/", HTTP_HOST="localhost")
        self.assertEqual(listing.status_code, 403)
        self.assertEqual(detail.status_code, 403)

    @patch("agent.mcp_tools.LocalMCPToolRunner.run")
    def test_disabling_tool_after_request_blocks_pending_approval_execution(self, mocked_run):
        tool = MCPTool.objects.get(name="web_search")
        tool.is_enabled = True
        tool.requires_approval = True
        tool.save(update_fields=["is_enabled", "requires_approval", "updated_at"])
        self.login_as(UserProfile.Role.OPERATOR)
        request = self.client.post(
            f"/api/agent/mcp-tools/{tool.pk}/execute/",
            {"query": "search"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(request.status_code, 202)
        approval_id = request.json()["approval"]["id"]
        self.login_as(UserProfile.Role.ADMIN)
        self.client.patch(
            f"/api/agent/mcp-tools/{tool.pk}/",
            {"is_enabled": False},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        approved = self.client.post(
            f"/api/agent/approvals/{approval_id}/",
            {"decision": "approve"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(ApprovalRequest.objects.get(pk=approval_id).status, ApprovalRequest.Status.FAILED)
        mocked_run.assert_not_called()
