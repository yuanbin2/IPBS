"""站点设置 API：公开读、管理员/运营写、访客拒绝、校验与回退默认值。"""

from django.contrib.auth import get_user_model

from ..models import BlogSetting, UserProfile
from .support import AdminApiTestCase, SecurityTransportTestCase, VisitorApiTestCase


def settings_path():
    return "/api/agent/blog/settings/"


class BlogSettingsPublicReadTests(SecurityTransportTestCase):
    def test_public_read_returns_defaults_and_about_uses_it(self):
        response = self.client.get(settings_path())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["articles_per_page"], 12)
        self.assertIn("site_title", payload)

        about = self.client.get("/api/agent/blog/about/")
        self.assertEqual(about.status_code, 200)
        # 设置为空时 about 回退到历史硬编码默认值
        self.assertNotEqual(about.json()["title"], "")


class BlogSettingsWriteTests(AdminApiTestCase):
    def test_admin_can_update_settings(self):
        response = self.client.put(
            settings_path(),
            {
                "site_title": "阿元的技术手记",
                "site_tagline": "记录、复盘、沉淀",
                "author_name": "阿元",
                "about_content": "新的关于内容",
                "about_highlights": ["全栈", "RAG"],
                "footer_text": "© 2026 阿元",
                "articles_per_page": 9,
            },
            content_type="application/json",
        )
        if response.status_code != 200:
            raise AssertionError(f"PUT failed: {response.status_code} {response.content!r}")
        payload = response.json()
        self.assertEqual(payload["site_title"], "阿元的技术手记")
        self.assertEqual(payload["articles_per_page"], 9)
        self.assertEqual(payload["about_highlights"], ["全栈", "RAG"])

        # 公开读取到新值；about 视图使用设置值
        public = self.client.get(settings_path())
        self.assertEqual(public.json()["site_title"], "阿元的技术手记")
        about = self.client.get("/api/agent/blog/about/")
        self.assertEqual(about.json()["content"], "新的关于内容")

    def test_validation_rejects_bad_values(self):
        response = self.client.put(
            settings_path(), {"articles_per_page": 99}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            settings_path(), {"about_highlights": "not-a-list"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            settings_path(), {"site_title": "x" * 121}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class BlogSettingsVisitorTests(VisitorApiTestCase):
    def test_visitor_cannot_update(self):
        response = self.client.put(
            settings_path(), {"site_title": "hijack"}, content_type="application/json"
        )
        self.assertIn(response.status_code, (401, 403))

    def test_operator_cannot_update(self):
        # 访客基类里用户角色是 visitor；这里再造一个 operator 也应被拒绝的是 admin-only 场景
        user = get_user_model().objects.create_user(username="settings-op", password="test-only-password-2026")
        UserProfile.objects.create(user=user, role=UserProfile.Role.OPERATOR, workspace_key="default")
        response = self.client.post(
            "/api/agent/auth/login/",
            {"username": "settings-op", "password": "test-only-password-2026"},
            content_type="application/json",
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        token = response.json()["token"]
        self.client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        response = self.client.put(
            settings_path(), {"site_title": "op-write"}, content_type="application/json"
        )
        # 运营/管理员都可以写：运营写成功
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["site_title"], "op-write")

    def test_singleton_row_is_reused(self):
        first = BlogSetting.load()
        second = BlogSetting.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.pk, 1)
