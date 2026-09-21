from .common import *


class AuthLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        if not username or not password:
            return Response({"detail": "username and password are required"}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response({"detail": "invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, user)
        tokens = issue_jwt_pair(user)
        profile = user.agent_profile
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "login succeeded",
            {"username": username, "role": profile.role},
        )
        return Response(
            {
                "token": tokens["access"],
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": serialize_user_profile(profile),
                "session": serialize_security_context(request),
            }
        )


class AuthRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        role = str(request.data.get("role", UserProfile.Role.ADMIN)).strip().lower()
        workspace_key = normalize_workspace_key(request.data.get("workspace_key", "default"))
        if not username or not password:
            return Response({"detail": "username and password are required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 8:
            return Response({"detail": "password must be at least 8 characters"}, status=status.HTTP_400_BAD_REQUEST)
        if role not in {UserProfile.Role.ADMIN, UserProfile.Role.OPERATOR, UserProfile.Role.VISITOR}:
            role = UserProfile.Role.ADMIN

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            return Response({"detail": "username already exists"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(username=username, password=password, is_staff=role == UserProfile.Role.ADMIN)
        profile, _ = UserProfile.objects.update_or_create(
            user=user,
            defaults={"role": role, "workspace_key": workspace_key},
        )
        tokens = issue_jwt_pair(user)
        audit_security_event(
            request,
            SecurityAuditEvent.EventType.LOGIN,
            "registration succeeded",
            {"username": username, "role": role, "workspace_key": workspace_key},
        )
        return Response(
            {
                "token": tokens["access"],
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": serialize_user_profile(profile),
                "session": {
                    "actor": user.username,
                    "role": profile.role,
                    "workspace_key": profile.workspace_key,
                    "authenticated": True,
                    "security_enforced": security_enforced(),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AuthMeView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(serialize_security_context(request))


class SecurityStatusView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        env_exists = (Path(settings.BASE_DIR).parent / ".env").exists()
        return Response(
            {
                "context": serialize_security_context(request),
                "checks": {
                    "security_enforced": security_enforced(),
                    "env_file_exists": env_exists,
                    "env_file_git_tracked": env_file_is_git_tracked(),
                    "debug": settings.DEBUG,
                    "allowed_hosts": settings.ALLOWED_HOSTS,
                    "langsmith_configured": bool(os.environ.get("LANGSMITH_API_KEY")),
                    "secret_values_returned": False,
                },
                "guidance": [
                    ".env 只保存在部署环境，不提交到 Git。",
                    "生产环境开启 AGENT_SECURITY_ENFORCED 并使用管理员账号登录。",
                    "工具默认白名单管理，高风险动作进入人工审批。",
                    "SQL 类能力只允许只读聚合查询。",
                ],
            }
        )


class SecurityAuditListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        workspace_key = get_workspace_key(request)
        events = SecurityAuditEvent.objects.filter(workspace_key=workspace_key)[:100]
        return Response([serialize_security_audit_event(event) for event in events])
