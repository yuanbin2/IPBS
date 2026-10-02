from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.agent_api.models import UserProfile


class Command(BaseCommand):
    help = "Create the operator account used by the isolated upload browser suite."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True)
        parser.add_argument("--username", default="upload-e2e-operator")
        parser.add_argument("--workspace", default="e2e-upload")
        parser.add_argument(
            "--role",
            choices=(UserProfile.Role.VISITOR, UserProfile.Role.OPERATOR, UserProfile.Role.ADMIN),
            default=UserProfile.Role.OPERATOR,
        )

    def handle(self, *args, password: str, username: str, workspace: str, role: str, **options):
        data_root = getattr(settings, "E2E_DATA_ROOT", None)
        if not getattr(settings, "E2E_TEST_MODE", False) or data_root is None:
            raise CommandError("This command is available only with config.settings_e2e.")

        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(
            username=username,
            defaults={"is_active": True},
        )
        user.is_active = True
        user.set_password(password)
        user.save(update_fields=["is_active", "password"])
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"role": role, "workspace_key": workspace},
        )
        self.stdout.write(f"Created isolated browser E2E operator {username}.")
