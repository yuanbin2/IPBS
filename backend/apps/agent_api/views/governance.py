from .common import *


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

    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        approval = get_object_or_404(ApprovalRequest, pk=pk, workspace_key=get_workspace_key(request))
        decision = str(request.data.get("decision", "")).strip().lower()
        reviewer = str(request.data.get("reviewer", "admin")).strip()
        note = str(request.data.get("note", "")).strip()

        if approval.status != ApprovalRequest.Status.PENDING:
            return Response(
                {"detail": "approval request is no longer pending"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if decision not in {"approve", "reject"}:
            return Response({"detail": "decision must be approve or reject"}, status=status.HTTP_400_BAD_REQUEST)

        approval.reviewer = reviewer
        approval.review_note = note
        approval.reviewed_at = timezone.now()

        if decision == "reject":
            approval.status = ApprovalRequest.Status.REJECTED
            approval.result = "人工审批已拒绝，敏感操作未执行。"
            approval.save(update_fields=["reviewer", "review_note", "reviewed_at", "status", "result"])
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
        return Response([serialize_mcp_tool(tool) for tool in tools])


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
            return Response({"detail": "tool is disabled"}, status=status.HTTP_400_BAD_REQUEST)
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

        execution = LocalMCPToolRunner(Path(settings.BASE_DIR).parent).run(tool.name, query)
        tool.last_used_at = timezone.now()
        tool.save(update_fields=["last_used_at", "updated_at"])
        return Response(
            {
                "tool": serialize_mcp_tool(tool),
                "input": execution.input,
                "output": execution.output,
            }
        )
