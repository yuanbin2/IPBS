"""Agent REST API：会话分页、消息持久化、审批和可观测性入口。"""

from .common import *


class ConversationListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        query = str(request.query_params.get("q", "")).strip()
        conversations = Conversation.objects.filter(
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        if query:
            conversations = conversations.filter(
                Q(title__icontains=query) | Q(messages__content__icontains=query)
            ).distinct()

        results = []
        for conversation in conversations[:30]:
            matched_message_id = None
            if query:
                match = conversation.messages.filter(content__icontains=query).first()
                matched_message_id = match.id if match else None
            results.append(
                serialize_conversation(
                    conversation,
                    matched_message_id=matched_message_id,
                )
            )
        return Response(results)


class ConversationDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, pk: int):
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        limit = get_message_limit(request)
        before = request.query_params.get("before")
        anchor = request.query_params.get("anchor")

        messages_queryset = conversation.messages.all()
        has_more_after = False

        if anchor:
            anchor_message = get_object_or_404(messages_queryset, pk=anchor)
            before_count = max(1, limit // 2)
            after_count = max(0, limit - before_count)
            before_messages = list(
                messages_queryset.filter(id__lte=anchor_message.id).order_by("-id")[:before_count]
            )
            after_messages = list(
                messages_queryset.filter(id__gt=anchor_message.id).order_by("id")[:after_count]
            )
            messages = [*reversed(before_messages), *after_messages]
            has_more_after = messages_queryset.filter(id__gt=messages[-1].id).exists() if messages else False
        elif before:
            messages = list(messages_queryset.filter(id__lt=before).order_by("-id")[:limit])
            messages = list(reversed(messages))
        else:
            messages = list(messages_queryset.order_by("-id")[:limit])
            messages = list(reversed(messages))

        has_more_before = messages_queryset.filter(id__lt=messages[0].id).exists() if messages else False
        return Response(
            serialize_conversation(
                conversation,
                include_messages=True,
                messages=messages,
                has_more_before=has_more_before,
                has_more_after=has_more_after,
            )
        )


class AgentChatView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        message = str(request.data.get("message", "")).strip()
        if not message:
            return Response(
                {"detail": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace_key = get_workspace_key(request)
        sensitive_marker = detect_sensitive_input(message)
        if sensitive_marker:
            audit_security_event(
                request,
                SecurityAuditEvent.EventType.SENSITIVE_INPUT,
                "chat input matched security filter",
                {"pattern": sensitive_marker},
            )

        # 会话同时按 workspace 和 owner 隔离，conversation_id 不能跨用户复用。
        conversation = self._get_or_create_conversation(
            request.data.get("conversation_id"),
            message,
            workspace_key,
            get_conversation_owner(request),
        )
        # 只把最近十条消息送入 Agent，既保留追问上下文，也控制 prompt 长度。
        history = [
            {"role": item.role, "content": item.content}
            for item in conversation.messages.order_by("-id")[:10][::-1]
        ]
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.USER,
            content=message,
        )

        # 高风险动作在调用 Supervisor 前转成审批单；当前 HTTP 请求只返回
        # 202，不直接执行删除或受控 MCP 工具。
        approval = maybe_create_blog_delete_approval(message, request) or maybe_create_mcp_approval(message, request)
        if approval:
            is_mcp_approval = approval.action == ApprovalRequest.Action.EXECUTE_MCP_TOOL
            response_data = {
                "answer": (
                    f"工具调用已进入人工审批 #{approval.id}：{approval.payload.get('tool_name')}"
                    if is_mcp_approval
                    else f"已为文章删除创建审批单 #{approval.id}。管理员批准后才会删除：{approval.payload.get('title')}"
                ),
                "tool_calls": [
                    {
                        "name": "mcp_approval" if is_mcp_approval else "admin_approval",
                        "input": message,
                        "output": f"approval_id={approval.id}; action={approval.action}",
                    }
                ],
                "sources": [],
                "trace": [
                    "supervisor -> received request",
                    "supervisor -> admin_approval_agent (blog deletion requires approval)",
                    "admin_approval_agent -> approval request created",
                ],
                "route": "admin_approval_agent",
                "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "supervisor": {
                    "selected_agent": "admin_approval_agent",
                    "display_name": "Admin Approval Agent",
                    "reason": "blog deletion requires human approval",
                    "confidence": 0.98,
                    "handoff": "handoff -> Admin Approval Agent",
                },
            }
            Message.objects.create(
                conversation=conversation,
                role=Message.Role.AGENT,
                content=response_data["answer"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            agent_run = AgentRun.objects.create(
                conversation=conversation,
                workspace_key=workspace_key,
                input_message=message,
                route=response_data["route"],
                tool_calls=response_data["tool_calls"],
                sources=response_data["sources"],
                trace=response_data["trace"],
                token_usage=response_data["token_usage"],
            )
            observation = create_agent_observation(
                conversation=conversation,
                agent_run=agent_run,
                input_message=message,
                workspace_key=workspace_key,
                response_data=response_data,
            )
            conversation.save(update_fields=["updated_at"])
            return Response(
                {
                    **response_data,
                    "approval_required": True,
                    "approval": serialize_approval_request(approval),
                    "conversation": serialize_conversation(conversation),
                    "observation": serialize_agent_observation(observation),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # REST 层只负责生命周期和持久化，真正的路由/工具/RAG 逻辑由
        # MultiAgentSupervisor 统一编排。
        project_root = Path(settings.BASE_DIR).parent
        started_at = time.perf_counter()
        try:
            agent = MultiAgentSupervisor(project_root, workspace_key=workspace_key)
            response = agent.chat(
                message,
                internet_enabled=bool(request.data.get("internet_enabled", False)),
                history=history,
            )
            response_data = response.to_dict()
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000)
            create_agent_observation(
                conversation=conversation,
                agent_run=None,
                input_message=message,
                workspace_key=workspace_key,
                latency_ms=latency_ms,
                failure_reason=str(exc),
            )
            raise

        # 将最终回答、工具轨迹、来源和 token 使用量一起保存，前端历史回放
        # 与可观测性页面因此不需要再次运行 Agent。
        Message.objects.create(
            conversation=conversation,
            role=Message.Role.AGENT,
            content=response.answer,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        agent_run = AgentRun.objects.create(
            conversation=conversation,
            workspace_key=workspace_key,
            input_message=message,
            route=response.route,
            tool_calls=response_data["tool_calls"],
            sources=response_data["sources"],
            trace=response.trace,
            token_usage=response.token_usage,
        )
        observation = create_agent_observation(
            conversation=conversation,
            agent_run=agent_run,
            input_message=message,
            workspace_key=workspace_key,
            response_data=response_data,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
        if any(item == "security_filter -> output redacted" for item in response.trace):
            audit_security_event(request, SecurityAuditEvent.EventType.OUTPUT_REDACTED, "agent output redacted")

        conversation.save(update_fields=["updated_at"])
        return Response(
            {
                **response_data,
                "conversation": serialize_conversation(conversation),
                "observation": serialize_agent_observation(observation),
            }
        )

    def _get_or_create_conversation(
        self,
        conversation_id,
        message: str,
        workspace_key: str,
        owner_username: str,
    ) -> Conversation:
        if conversation_id:
            return get_object_or_404(
                Conversation,
                pk=conversation_id,
                workspace_key=workspace_key,
                owner_username=owner_username,
            )

        title = message[:40]
        if len(message) > 40:
            title = f"{title}..."
        return Conversation.objects.create(
            title=title,
            workspace_key=workspace_key,
            owner_username=owner_username,
        )


class ObservabilityDashboardView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        limit = min(int(request.query_params.get("limit", 30)), 100)
        observations = AgentObservation.objects.select_related("conversation", "agent_run").filter(
            workspace_key=get_workspace_key(request)
        )[:limit]
        return Response(
            {
                "summary": observability_summary(get_workspace_key(request)),
                "observations": [serialize_agent_observation(observation) for observation in observations],
            }
        )


class EvaluationCaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        category = request.query_params.get("category")
        cases = EvaluationCase.objects.prefetch_related("runs").filter(workspace_key=get_workspace_key(request))
        if category and category != "all":
            cases = cases.filter(category=category)
        return Response([serialize_evaluation_case(case) for case in cases])


class EvaluationRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        case_id = request.data.get("case_id")
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 30))
        except (TypeError, ValueError):
            limit = 5

        workspace_key = get_workspace_key(request)
        if case_id:
            cases = [get_object_or_404(EvaluationCase, pk=case_id, workspace_key=workspace_key)]
        else:
            cases = list(EvaluationCase.objects.filter(is_active=True, workspace_key=workspace_key)[:limit])

        runs = [self._run_case(case) for case in cases]
        passed_count = sum(1 for run in runs if run.passed)
        return Response(
            {
                "total": len(runs),
                "passed": passed_count,
                "pass_rate": round(passed_count / len(runs), 2) if runs else 0,
                "runs": [serialize_evaluation_run(run) for run in runs],
            }
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationRun:
        started_at = time.perf_counter()
        try:
            response = MultiAgentSupervisor(Path(settings.BASE_DIR).parent).chat(case.question)
            response_data = response.to_dict()
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                response_data=response_data,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )
            metrics = evaluate_answer(case, response_data, observation)
            passed = (
                metrics["answer_correctness"] >= 0.6
                and metrics["faithfulness"] >= 0.7
                and metrics["tool_success_rate"] >= 0.8
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer=response_data.get("answer", ""),
                metrics=metrics,
                passed=passed,
            )
        except Exception as exc:
            observation = create_agent_observation(
                conversation=None,
                agent_run=None,
                input_message=case.question,
                workspace_key=case.workspace_key,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                failure_reason=str(exc),
            )
            return EvaluationRun.objects.create(
                case=case,
                workspace_key=case.workspace_key,
                observation=observation,
                answer="",
                metrics={
                    "answer_correctness": 0,
                    "faithfulness": 0,
                    "citation_accuracy": 0,
                    "latency_ms": observation.latency_ms,
                    "tool_success_rate": 0,
                    "failure_reason": str(exc),
                },
                passed=False,
            )
