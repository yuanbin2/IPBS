from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..exceptions import ErrorCode
from ..models import ApprovalRequest, BlogArticle, BlogArticleRevision, MCPTool, UserProfile
from ..serializers import serialize_approval_request, serialize_mcp_tool
from .common import (
    approval_required_response,
    ensure_default_mcp_tools,
    error_response,
    execute_approval_request,
    get_workspace_key,
    require_roles,
)


class ApprovalRequestListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        status_filter = request.query_params.get("status", "pending")
        approvals = ApprovalRequest.objects.filter(workspace_key=get_workspace_key(request))
        if status_filter != "all":
            approvals = approvals.filter(status=status_filter)
        return Response([serialize_approval_request(approval) for approval in approvals[:100]])


class ApprovalRequestDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    @transaction.atomic
    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        approval = get_object_or_404(
            ApprovalRequest.objects.select_for_update(), pk=pk, workspace_key=get_workspace_key(request)
        )
        decision = str(request.data.get("decision", "")).strip().lower()
        reviewer = str(request.data.get("reviewer", "admin")).strip()
        note = str(request.data.get("note", "")).strip()

        if approval.status != ApprovalRequest.Status.PENDING:
            return error_response(
                "approval request is no longer pending", ErrorCode.CONFLICT, status.HTTP_400_BAD_REQUEST
            )
        if decision not in {"approve", "reject"}:
            return error_response(
                "decision must be approve or reject", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        approval.reviewer = reviewer
        approval.review_note = note
        approval.reviewed_at = timezone.now()

        if decision == "reject":
            approval.status = ApprovalRequest.Status.REJECTED
            approval.result = "人工审批已拒绝，敏感操作未执行。"
            approval.save(update_fields=["reviewer", "review_note", "reviewed_at", "status", "result"])

            # 如果是博客发布审批被拒绝，更新文章状态
            if approval.action == ApprovalRequest.Action.PUBLISH_BLOG_ARTICLE:
                revision_id = approval.payload.get("revision_id")
                if revision_id is not None:
                    BlogArticleRevision.objects.filter(
                        pk=revision_id,
                        article__workspace_key=get_workspace_key(request),
                        status=BlogArticleRevision.Status.PENDING,
                    ).update(status=BlogArticleRevision.Status.REJECTED, reviewed_at=timezone.now())
                    return Response(serialize_approval_request(approval))
                article_slug = approval.payload.get("article_slug")
                if article_slug:
                    BlogArticle.objects.filter(
                        slug=article_slug,
                        workspace_key=get_workspace_key(request),
                    ).exclude(
                        status=BlogArticle.Status.PUBLISHED
                    ).update(status=BlogArticle.Status.REJECTED)

            # 目录发布被拒：清理失效的待审快照，公开旧版与私有草稿保持不变
            if approval.action == ApprovalRequest.Action.PUBLISH_BLOG_COLLECTION:
                from ..models import BlogCollection

                BlogCollection.objects.filter(
                    pk=approval.payload.get("collection_id"),
                    workspace_key=get_workspace_key(request),
                    pending_approval=approval,
                ).update(pending_snapshot=None, pending_approval=None, updated_at=timezone.now())

            return Response(serialize_approval_request(approval))

        try:
            approval.result = execute_approval_request(approval)
            approval.status = ApprovalRequest.Status.EXECUTED
            approval.executed_at = timezone.now()
        except Exception as exc:
            approval.result = str(exc)
            approval.status = ApprovalRequest.Status.FAILED
        approval.save(update_fields=["reviewer", "review_note", "reviewed_at", "status", "result", "executed_at"])
        return Response(serialize_approval_request(approval))


class MCPToolListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        ensure_default_mcp_tools()
        tools = MCPTool.objects.filter(workspace_key=get_workspace_key(request))

        # 计算统计概览
        total_count = tools.count()
        enabled_count = tools.filter(is_enabled=True).count()
        total_calls = sum(t.call_count for t in tools)
        total_success = sum(t.success_count for t in tools)
        avg_success_rate = (total_success / total_calls * 100) if total_calls > 0 else 100

        return Response(
            {
                "tools": [serialize_mcp_tool(tool) for tool in tools],
                "summary": {
                    "total_count": total_count,
                    "enabled_count": enabled_count,
                    "total_calls": total_calls,
                    "avg_success_rate": round(avg_success_rate, 1),
                },
            }
        )


class MCPToolDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def patch(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        tool = get_object_or_404(MCPTool, pk=pk, workspace_key=get_workspace_key(request))
        if "is_enabled" in request.data:
            tool.is_enabled = bool(request.data["is_enabled"])
        if "requires_approval" in request.data:
            tool.requires_approval = bool(request.data["requires_approval"])
        if "permission_scope" in request.data:
            tool.permission_scope = str(request.data["permission_scope"]).strip()
        tool.save(update_fields=["is_enabled", "requires_approval", "permission_scope", "updated_at"])
        return Response(serialize_mcp_tool(tool))


class MCPToolExecuteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        from agent.mcp_tools import LocalMCPToolRunner

        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        tool = get_object_or_404(MCPTool, pk=pk, workspace_key=get_workspace_key(request))
        query = str(request.data.get("query", "")).strip()
        if not tool.is_enabled:
            return error_response("tool is disabled", ErrorCode.CONFLICT, status.HTTP_400_BAD_REQUEST)
        if tool.requires_approval:
            approval = ApprovalRequest.objects.create(
                action=ApprovalRequest.Action.EXECUTE_MCP_TOOL,
                workspace_key=get_workspace_key(request),
                title=f"执行 MCP 工具：{tool.display_name}",
                description=f"工具权限范围：{tool.permission_scope}",
                payload={"tool_id": tool.id, "tool_name": tool.name, "query": query},
                requester=str(request.data.get("requester", "operator")).strip(),
            )
            return approval_required_response(approval)

        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent, workspace_key=get_workspace_key(request)).run(
            tool.name, query
        )
        tool.last_used_at = timezone.now()
        tool.call_count += 1
        if execution.output and "error" not in execution.output.lower():
            tool.success_count += 1
        tool.save(update_fields=["last_used_at", "call_count", "success_count", "updated_at"])
        return Response(
            {
                "tool": serialize_mcp_tool(tool),
                "input": execution.input,
                "output": execution.output,
            }
        )


class MCPToolHealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        """执行单个工具的健康检查"""
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        tool = get_object_or_404(MCPTool, pk=pk, workspace_key=get_workspace_key(request))

        try:
            from agent.mcp_tools import LocalMCPToolRunner

            runner = LocalMCPToolRunner(Path(settings.BASE_DIR).parent, workspace_key=get_workspace_key(request))

            # 尝试执行一个简单的测试查询
            test_query = "health check test"
            execution = runner.run(tool.name, test_query)

            if execution.output and "error" not in execution.output.lower():
                tool.health_status = MCPTool.HealthStatus.HEALTHY
                tool.health_message = "工具运行正常"
            else:
                tool.health_status = MCPTool.HealthStatus.WARNING
                tool.health_message = execution.output[:200] if execution.output else "无输出"
        except Exception as e:
            tool.health_status = MCPTool.HealthStatus.ERROR
            tool.health_message = str(e)[:200]

        tool.last_health_check = timezone.now()
        tool.save(update_fields=["health_status", "health_message", "last_health_check", "updated_at"])
        return Response(serialize_mcp_tool(tool))


class MCPToolBulkHealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """批量健康检查所有工具"""
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied

        tools = MCPTool.objects.filter(workspace_key=get_workspace_key(request), is_enabled=True)

        from agent.mcp_tools import LocalMCPToolRunner

        runner = LocalMCPToolRunner(Path(settings.BASE_DIR).parent, workspace_key=get_workspace_key(request))

        results = []
        for tool in tools:
            try:
                test_query = "health check test"
                execution = runner.run(tool.name, test_query)

                if execution.output and "error" not in execution.output.lower():
                    tool.health_status = MCPTool.HealthStatus.HEALTHY
                    tool.health_message = "工具运行正常"
                else:
                    tool.health_status = MCPTool.HealthStatus.WARNING
                    tool.health_message = execution.output[:200] if execution.output else "无输出"
            except Exception as e:
                tool.health_status = MCPTool.HealthStatus.ERROR
                tool.health_message = str(e)[:200]

            tool.last_health_check = timezone.now()
            tool.save(update_fields=["health_status", "health_message", "last_health_check", "updated_at"])
            results.append(serialize_mcp_tool(tool))

        return Response(results)
