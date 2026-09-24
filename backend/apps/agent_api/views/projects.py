"""对话项目：创建/重命名/删除分组，以及把会话移入/移出项目。"""

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from ..exceptions import ErrorCode
from ..models import Conversation, ConversationProject
from ..serializers import serialize_conversation, serialize_project
from .common import error_response, get_conversation_owner, get_workspace_key

MAX_PROJECTS_PER_OWNER = 50


class ConversationProjectListCreateView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        projects = ConversationProject.objects.filter(
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        return Response([serialize_project(project) for project in projects[:MAX_PROJECTS_PER_OWNER]])

    def post(self, request):
        name = str(request.data.get("name", "")).strip()[:120]
        if not name:
            return error_response("name is required", ErrorCode.MISSING_FIELD, 400)

        owner = get_conversation_owner(request)
        workspace_key = get_workspace_key(request)
        exists = ConversationProject.objects.filter(
            workspace_key=workspace_key,
            owner_username=owner,
            name=name,
        ).exists()
        if exists:
            return error_response("project name already exists", ErrorCode.CONFLICT, 409)

        project = ConversationProject.objects.create(
            name=name,
            description=str(request.data.get("description", "")).strip(),
            color=str(request.data.get("color", "teal")).strip()[:20],
            workspace_key=workspace_key,
            owner_username=owner,
        )
        return Response(serialize_project(project), status=201)


class ConversationProjectDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def patch(self, request, pk: int):
        project = get_object_or_404(
            ConversationProject,
            pk=pk,
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        name = str(request.data.get("name", "")).strip()[:120]
        if "name" in request.data:
            if not name:
                return error_response("name is required", ErrorCode.MISSING_FIELD, 400)
            project.name = name
        if "description" in request.data:
            project.description = str(request.data["description"]).strip()
        if "color" in request.data:
            project.color = str(request.data["color"]).strip()[:20]
        project.save()
        return Response(serialize_project(project))

    def delete(self, request, pk: int):
        project = get_object_or_404(
            ConversationProject,
            pk=pk,
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        # SET_NULL：项目删除后其中的对话回到「未分组」，不丢历史
        project.delete()
        return Response(status=204)


class ConversationMoveView(APIView):
    """把会话移入某个项目，或传 project_id=null 移出到未分组。"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        conversation = get_object_or_404(
            Conversation,
            pk=pk,
            workspace_key=get_workspace_key(request),
            owner_username=get_conversation_owner(request),
        )
        project_id = request.data.get("project_id")
        if project_id in (None, "", "none"):
            conversation.project = None
        else:
            project = get_object_or_404(
                ConversationProject,
                pk=project_id,
                workspace_key=get_workspace_key(request),
                owner_username=get_conversation_owner(request),
            )
            conversation.project = project
        conversation.save(update_fields=["project", "updated_at"])
        return Response(serialize_conversation(conversation))
