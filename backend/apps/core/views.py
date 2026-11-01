from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "status": "ok",
                "service": "smart-personal-blog",
                "modules": ["blog", "knowledge-base", "agent", "rag", "mcp"],
            }
        )


class ReadyCheckView(APIView):
    """Report database and schema readiness separately from process liveness."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            connection = connections["default"]
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            executor = MigrationExecutor(connection)
            if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                return Response(
                    {"status": "unavailable", "reason": "pending_migrations"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        except Exception:
            return Response(
                {"status": "unavailable", "reason": "database_or_schema"}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        return Response({"status": "ready"})
