"""检索后重排（rerank）的纯逻辑回归。

覆盖目标：强信号（实体/标题命中）能把被向量噪声压在后面的正确文档提到前面，
且不改动入参、空输入不炸、权重为 0 时完全保持原顺序。
融合权重本身的标定另见缺陷表 B-056。
"""

from django.test import SimpleTestCase

from ..services.rag import (
    RERANK_AFFILIATION_WEIGHT,
    RERANK_SCORE_WEIGHT,
    SearchResult,
    query_entity_terms,
    rerank_search_results,
    rerank_signal,
)


def result(document_id: int, chunk_id: int, title: str, content: str, score: float) -> SearchResult:
    return SearchResult(
        document_id=document_id,
        document_title=title,
        chunk_id=chunk_id,
        chunk_index=chunk_id,
        content=content,
        score=score,
    )


class RerankSignalTests(SimpleTestCase):
    def test_entity_in_title_scores_higher_than_in_content_only(self):
        query = "卫晓斌属于哪个学校"
        in_title = rerank_signal(query, "卫晓斌_全栈工程师", "教育经历：重庆三峡科技大学")
        in_content = rerank_signal(query, "项目文档", "联系人：卫晓斌，邮箱 wxb@example.com")
        self.assertGreater(in_title, in_content)

    def test_no_signal_returns_low_score(self):
        signal = rerank_signal("介绍一下散射成像的原理", "面试鸭面经汇总", "本文整理了常见面试题")
        self.assertLess(signal, 0.4)

    def test_signal_is_capped_at_one(self):
        signal = rerank_signal("卫晓斌", "卫晓斌", "卫晓斌 卫晓斌 卫晓斌")
        self.assertLessEqual(signal, 1.0)

    def test_signal_never_negative(self):
        self.assertGreaterEqual(rerank_signal("", "", ""), 0.0)

    def test_affiliation_query_promotes_chunk_with_education_signal(self):
        # 同一文档的切片：含「大学/硕士」等教育信号的应排在前面。
        education = "教育经历：重庆三峡科技大学 硕士 计算机技术 2024-2027"
        project = "项目经历：智能个人博客系统全栈开发 2026.05-2026.09"
        query = "卫晓斌属于哪个学校"
        self.assertGreater(
            rerank_signal(query, "卫晓斌_全栈工程师", education),
            rerank_signal(query, "卫晓斌_全栈工程师", project),
        )

    def test_education_bonus_only_for_affiliation_queries(self):
        # 同一份含教育信号的切片：归属类问句应比普通问句得分更高。
        education = "教育经历：重庆三峡科技大学 硕士 计算机技术"
        self.assertGreater(
            rerank_signal("卫晓斌属于哪个学校", "卫晓斌_全栈工程师", education),
            rerank_signal("介绍一下卫晓斌", "卫晓斌_全栈工程师", education),
        )

    def test_precomputed_entity_terms_match_internal_extraction(self):
        query = "卫晓斌毕业于哪个学校"
        self.assertEqual(
            rerank_signal(query, "卫晓斌_全栈工程师", "教育经历"),
            rerank_signal(query, "卫晓斌_全栈工程师", "教育经历", query_entity_terms(query)),
        )


class RerankSearchResultTests(SimpleTestCase):
    def test_rerank_promotes_weakly_scored_but_entity_matching_document(self):
        # 复刻 B-055 的放大器场景：长文档靠噪声占 Top-1，简历实体命中却被压在后面。
        noisy = result(1, 101, "模块 01：Python 与工程基础", "本文讲 Python 工程实践与目录结构", 0.11)
        resume = result(2, 102, "卫晓斌_全栈工程师", "教育经历：重庆三峡科技大学 硕士 计算机技术", 0.09)
        ranked = rerank_search_results("卫晓斌属于哪个学校", [noisy, resume])
        self.assertEqual([item.document_id for item in ranked], [2, 1])
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_rerank_does_not_mutate_input(self):
        original = result(1, 1, "标题", "正文", 0.5)
        rerank_search_results("标题", [original])
        self.assertEqual(original.score, 0.5)

    def test_zero_weight_keeps_original_order(self):
        first = result(1, 1, "甲", "内容甲", 0.8)
        second = result(2, 2, "乙", "内容乙", 0.4)
        ranked = rerank_search_results("甲", [first, second], weight=0)
        self.assertEqual([item.chunk_id for item in ranked], [1, 2])
        self.assertEqual(ranked[0].score, 0.8)

    def test_empty_results(self):
        self.assertEqual(rerank_search_results("任意问题", []), [])

    def test_scores_stay_within_zero_and_one(self):
        ranked = rerank_search_results(
            "卫晓斌",
            [result(1, 1, "卫晓斌", "卫晓斌", 1.0), result(2, 2, "无关", "无关内容", 0.0)],
        )
        for item in ranked:
            self.assertGreaterEqual(item.score, 0.0)
            self.assertLessEqual(item.score, 1.0)

    def test_default_weight_matches_module_constant(self):
        # 防止有人只改常量却忘了同步默认值。
        self.assertEqual(RERANK_SCORE_WEIGHT, 0.4)

    def test_rerank_preserves_all_items_and_metadata(self):
        items = [
            result(1, 1, "甲", "内容甲", 0.5),
            result(2, 2, "乙", "内容乙", 0.3),
            result(3, 3, "丙", "内容丙", 0.1),
        ]
        ranked = rerank_search_results("甲", items)
        self.assertEqual(sorted(item.chunk_id for item in ranked), [1, 2, 3])
        self.assertEqual([item.document_title for item in ranked], ["甲", "乙", "丙"])
