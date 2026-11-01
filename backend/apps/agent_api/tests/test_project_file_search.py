"""「本地文件搜索」（local_file_search）工具的检索范围与排序测试。

回归背景：老实现硬编码 5 个源文件，其中 3 个 day-0X 笔记早已不存在，
docs/ 下的设计、API、缺陷跟踪文档全部搜不到，工具几乎零召回。
"""

from pathlib import Path

from django.test import SimpleTestCase

from agent.tools import (
    PROJECT_DOC_MAX_MATCHES,
    collect_project_doc_files,
    search_project_files,
    split_search_terms,
)


class ProjectFileSearchTests(SimpleTestCase):
    def build_docs(self, root: Path):
        (root / "README.md").write_text("项目入口说明：包含部署与迁移入口。", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "api.md").write_text(
            "# API\n\nGET /auth/me/ 返回当前身份。\nGET /security/status/ 需要管理员。\n",
            encoding="utf-8",
        )
        (root / "docs" / "缺陷跟踪表.md").write_text(
            "# 缺陷跟踪表\n\nB-064 拖拽排序未完成。\nB-067 导出包图片路径错误。\n",
            encoding="utf-8",
        )
        (root / "docs" / "nested").mkdir()
        (root / "docs" / "nested" / "deep.md").write_text("深层文档也应当被检索到。", encoding="utf-8")
        # 构建产物目录必须被跳过。
        (root / "docs" / "node_modules").mkdir()
        (root / "docs" / "node_modules" / "pkg.md").write_text("不应被检索到的依赖文档。", encoding="utf-8")

    def test_collect_project_doc_files_covers_readme_and_all_docs_markdown(self):
        root = Path(self.root_path("collect"))
        self.build_docs(root)
        collected = [path.relative_to(root).as_posix() for path in collect_project_doc_files(root)]
        self.assertIn("README.md", collected)
        self.assertIn("docs/api.md", collected)
        self.assertIn("docs/nested/deep.md", collected)
        self.assertNotIn("docs/node_modules/pkg.md", collected)

    def test_search_hits_docs_beyond_the_old_hardcoded_files(self):
        root = Path(self.root_path("hits"))
        self.build_docs(root)
        # 老实现只能搜到 README，缺陷跟踪文档里的条目根本进不来。
        output = search_project_files(root, "拖拽")
        self.assertIn("docs/缺陷跟踪表.md:", output)
        self.assertIn("B-064", output)

    def test_search_returns_file_and_line_for_locating(self):
        root = Path(self.root_path("line"))
        self.build_docs(root)
        output = search_project_files(root, "security")
        self.assertIn("docs/api.md:4:", output)

    def test_search_is_not_capped_by_the_first_matching_file(self):
        root = Path(self.root_path("multi"))
        self.build_docs(root)
        output = search_project_files(root, "拖")  # 常见于多个文档的关键词
        body = [line for line in output.splitlines() if ":" in line]
        self.assertLessEqual(len(body), PROJECT_DOC_MAX_MATCHES)

        # 同一个查询的多个来源都要出现，不能只返回第一个文件的结果。
        both = search_project_files(root, "文档")
        self.assertTrue(both.splitlines()[1:])

    def test_search_respects_match_limit(self):
        root = Path(self.root_path("limit"))
        (root / "README.md").write_text("重复行\n" * 60, encoding="utf-8")
        output = search_project_files(root, "重复行")
        self.assertIn(f"命中 {PROJECT_DOC_MAX_MATCHES} 条", output)

    def test_empty_query_lists_searchable_documents(self):
        root = Path(self.root_path("empty"))
        self.build_docs(root)
        output = search_project_files(root, "   ")
        self.assertIn("请提供检索关键词", output)
        self.assertIn("docs/api.md", output)

    def test_missing_docs_directory_does_not_break(self):
        root = Path(self.root_path("missing"))
        (root / "README.md").write_text("只有 README 的项目。", encoding="utf-8")
        output = search_project_files(root, "README")
        self.assertIn("README.md:1:", output)

    def test_no_match_message_states_the_scope(self):
        root = Path(self.root_path("nomatch"))
        self.build_docs(root)
        output = search_project_files(root, "绝不可能出现的关键词xyz")
        self.assertIn("没有找到匹配", output)
        self.assertIn("个 Markdown 文档", output)

    def test_split_search_terms_adds_cjk_bigrams(self):
        terms = split_search_terms("缺陷 跟踪 B-064")
        self.assertIn("缺陷", terms)
        self.assertIn("跟踪", terms)
        self.assertIn("b-064", terms)
        # 重复 2-gram 不应重复计入评分。
        self.assertEqual(len(terms), len(set(terms)))

    def root_path(self, name: str) -> str:
        import tempfile

        path = Path(tempfile.mkdtemp(prefix=f"project-file-search-{name}-"))
        self.addCleanup(lambda: self.remove_tree(path))
        return str(path)

    @staticmethod
    def remove_tree(path: Path) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
