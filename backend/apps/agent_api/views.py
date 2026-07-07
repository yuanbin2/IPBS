from pathlib import Path

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.simple_agent import SimpleToolCallingAgent


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

        project_root = Path(settings.BASE_DIR).parent
        agent = SimpleToolCallingAgent(project_root)
        response = agent.chat(message)
        return Response(response.to_dict())

