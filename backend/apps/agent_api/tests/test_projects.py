"""对话项目：分组 CRUD、会话移动与按项目过滤。"""

from unittest.mock import patch

from django.test import TestCase

from ..models import Conversation, ConversationProject
from .support import NO_MODEL_ENV


class ConversationProjectTests(TestCase):

    def _create_project(self, name: str = "LangGraph 学习") -> dict:
        response = self.client.post(
            "/api/agent/projects/",
            {"name": name, "description": "阶段性笔记"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_create_and_list_projects(self):
        created = self._create_project()

        response = self.client.get("/api/agent/projects/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "LangGraph 学习")
        self.assertEqual(payload[0]["conversation_count"], 0)
        self.assertEqual(payload[0]["id"], created["id"])

    def test_create_project_requires_name(self):
        response = self.client.post(
            "/api/agent/projects/",
            {"description": "no name"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "missing_field")

    def test_duplicate_project_name_conflicts(self):
        self._create_project("dup")

        response = self.client.post(
            "/api/agent/projects/",
            {"name": "dup"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "conflict")

    def test_rename_project(self):
        project = self._create_project("old name")

        response = self.client.patch(
            f"/api/agent/projects/{project['id']}/",
            {"name": "new name"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "new name")

    def test_delete_project_keeps_conversations_ungrouped(self):
        project = self._create_project("to delete")
        conversation = Conversation.objects.create(title="inside")
        conversation.project_id = project["id"]
        conversation.save(update_fields=["project"])

        response = self.client.delete(
            f"/api/agent/projects/{project['id']}/",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 204)
        conversation.refresh_from_db()
        self.assertIsNone(conversation.project_id)
        self.assertTrue(Conversation.objects.filter(pk=conversation.pk).exists())

    def test_move_conversation_into_and_out_of_project(self):
        project = self._create_project("target")
        conversation = Conversation.objects.create(title="movable")

        move_in = self.client.post(
            f"/api/agent/conversations/{conversation.id}/move/",
            {"project_id": project["id"]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(move_in.status_code, 200)
        self.assertEqual(move_in.json()["project_id"], project["id"])

        move_out = self.client.post(
            f"/api/agent/conversations/{conversation.id}/move/",
            {"project_id": None},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(move_out.status_code, 200)
        self.assertIsNone(move_out.json()["project_id"])

    def test_move_to_foreign_project_is_rejected(self):
        other_owner_project = ConversationProject.objects.create(
            name="someone else",
            workspace_key="default",
            owner_username="another-user",
        )
        conversation = Conversation.objects.create(title="mine")

        response = self.client.post(
            f"/api/agent/conversations/{conversation.id}/move/",
            {"project_id": other_owner_project.id},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 404)
        conversation.refresh_from_db()
        self.assertIsNone(conversation.project_id)

    def test_conversation_list_filters_by_project(self):
        project = self._create_project("filtered")
        inside = Conversation.objects.create(title="inside project")
        inside.project_id = project["id"]
        inside.save(update_fields=["project"])
        Conversation.objects.create(title="outside project")

        in_project = self.client.get(
            f"/api/agent/conversations/?project={project['id']}",
            HTTP_HOST="localhost",
        ).json()
        ungrouped = self.client.get(
            "/api/agent/conversations/?project=none",
            HTTP_HOST="localhost",
        ).json()

        self.assertEqual([item["title"] for item in in_project], ["inside project"])
        self.assertEqual([item["title"] for item in ungrouped], ["outside project"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_new_chat_lands_in_selected_project(self):
        project = self._create_project("chat home")

        response = self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 6 * 7", "project_id": project["id"]},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        conversation_id = response.json()["conversation"]["id"]
        conversation = Conversation.objects.get(pk=conversation_id)
        self.assertEqual(conversation.project_id, project["id"])

    @patch.dict("os.environ", NO_MODEL_ENV)
    def test_new_chat_with_unknown_project_stays_ungrouped(self):
        response = self.client.post(
            "/api/agent/chat/",
            {"message": "帮我计算 6 * 7", "project_id": 999999},
            content_type="application/json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(response.status_code, 200)
        conversation_id = response.json()["conversation"]["id"]
        conversation = Conversation.objects.get(pk=conversation_id)
        self.assertIsNone(conversation.project_id)
