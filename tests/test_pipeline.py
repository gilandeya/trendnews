"""اختبار الأنبوب كاملًا بمحاكاة الشبكة و Claude API (بلا أي طلب خارجي).

    python -m tests.test_pipeline
"""
from __future__ import annotations

from tests.helpers import FAILED, PASSED, install_fakes
from tests.test_collect import (
    test_tokens_and_similarity,
    test_fetch_and_filter,
    test_image_filtering,
    test_image_report,
    test_card_second_badge_by_origin,
    test_google_news_link_decode,
    test_trends,
    test_state_media,
    test_velocity,
    test_velocity_in_ranking,
    test_followups,
    test_find_previous_prefers_posted_over_offered,
    test_bucket_quotas,
    test_editorial_guardrails,
    test_extraction,
    test_analysis_grounding,
    test_analysis_cleaning,
    test_cluster_members,
    test_useful_bucket,
    test_health_guardrails,
    test_dedupe_memory,
    test_dedupe_threshold_separation,
    test_screen_merge_missing_api_key,
    test_appeal_factors,
    test_appeal_factors_affect_ranking,
    test_radar_gate_check_dedupe,
    test_radar_preselect_fallback,
    test_radar_auto_publish_builds_card,
    test_collect_end_to_end,
    test_arabic_shaping,
    test_no_temperature_param,
    test_writer_usage_summary_cache_ratio,
)
from tests.test_review import (
    test_review_roundtrip,
    test_preselect_no_spend_before_selection,
    test_preselect_no_duplicate_across_runs,
    test_preselect_finalize,
    test_preselect_now_builds_card_before_publish,
    test_preselect_now_card_build_failure_keeps_pending,
    test_preselect_empty_selection_no_spend,
    test_preselect_drops_stale_candidates,
    test_preselect_two_boxes_now_and_draft_review,
    test_preselect_draft_review_image_swap_works,
    test_preselect_card_marker_and_selected_card_ids,
    test_preselect_card_only_and_three_way_conflicts,
    test_preselect_card_build_failure_keeps_pending,
    test_preselect_translate_titles,
    test_finalize_format_mismatch_no_silent_fail,
    test_publish_conflicting_labels_no_dispatch,
    test_writer_classifies_write_errors,
    test_finalize_external_failure_keeps_approved_no_feedback,
    test_finalize_editorial_rejection_removes_approved,
    test_publish_pending_selection_single_dispatch,
    test_manual_image,
    test_editable_caption_and_image_source,
    test_setimage_revives_failed_draft_only_when_image_was_the_cause,
    test_setimage_stores_manual_link_without_card,
    test_setimage_cli_sync_handles_cardless_draft,
    test_setimage_apply_image_keeps_origin_badge,
    test_publish_builds_cards_at_approval,
    test_request_search,
    test_request_and_radar_headlines,
    test_headlines_module,
    test_headlines_failure_keeps_draft_with_empty_list,
    test_review_sibling_alternate_line,
    test_setimage_rebuild_card_uses_all_image_candidates,
    test_publish_investigation_requires_review,
    test_no_reject_boxes_in_review_issues,
    test_publish_unapproved_becomes_rejected,
    test_review_card_and_back_boxes,
    test_publish_card_request_defers_to_final_review,
    test_publish_final_review_approve_publishes_without_rebuild,
    test_publish_final_review_double_publish_guard,
    test_publish_final_review_back_request,
    test_publish_final_review_excludes_analysis_origin,
    test_first_comment,
    test_burst_inline_cap_zero_defers_without_sleep,
    test_burst_urgent_still_immediate_with_inline_cap_zero,
    test_scheduling,
    test_due_publishes_one_at_a_time,
    test_publish_skips_broken_draft_without_stopping_batch,
    test_burst_skips_broken_draft_without_spacing_sleep,
    test_publish_routes_youtube_origin_by_field_not_label,
    test_publish_routes_news_origin_unaffected,
    test_publish_routes_mixed_origins_in_same_issue,
    test_publish_urgent_only_defers_youtube_to_normal_job,
    test_open_review_excludes_youtube_and_broken_drafts,
    test_review_sort_by_score,
    test_open_review_orders_drafts_by_score,
    test_open_review_orders_candidates_by_score,
    test_publish_final_review_orders_by_score,
    test_collect_finalize_card_review_orders_by_score,
    test_origin_of_synonyms,
    test_feedback_records_origin_and_screening_guidance_excludes_analysis,
    test_feedback_screening_guidance_excludes_not_selected,
    test_radar_writes_breaking_origin,
    test_request_writes_request_origin,
    test_decisions,
    test_insights_analysis,
    test_insights_collect_includes_analysis_origin,
    test_insights_weakest_performing_section,
    test_insights_rejections_section,
    test_insights_recommendation_ids_and_choice_parsing,
    test_insights_sync_does_not_refresh_unchanged_decision,
    test_insights_closed_loop,
    test_insights_why_not_published_section,
    test_insights_parse_reason_choices,
    test_insights_reason_choice_updates_rejection_and_feeds_screening,
    test_insights_why_entry_shown_twice_then_drops,
    test_insights_reason_entry_id_stable_despite_order,
    test_insights_why_section_missing_state_file,
    test_insights_no_posts_still_shows_why_and_decisions,
    test_collect_feedback_rejects_analysis_draft_without_image,
)
from tests.test_article import (
    test_verify,
    test_verify_draft,
    test_check_originality_signals,
    test_check_originality_trim,
    test_check_originality_context,
    test_check_originality_wa_pronoun_and_min_core_revert,
    test_check_originality_quantity,
    test_check_originality_name_link,
    test_check_originality_grounded,
    test_check_originality_offending,
    test_evidence,
    test_article,
    test_article_statement_kind,
    test_article_merged_statement_gaps,
    test_article_statement_majority,
    test_article_split_statements,
    test_article_split_event_condition,
    test_article_mandatory_query_name,
    test_article_search_ladder,
    test_article_read_failure_substitution,
    test_article_wide_days,
    test_article_support_call_caching,
    test_article_source_fact_duplicate_index_on_topic,
    test_article_source_fact_topic_guard,
    test_article_source_fact_topic_guard_call_failure_admits,
    test_article_report_kind,
    test_article_generic_source_publisher,
    test_article_unsourced_entities,
    test_evidence_top_candidates,
    test_evidence_relevance_cap,
    test_evidence_relevance_display_matches_score,
    test_article_duplicate_query_reuse,
    test_article_longest_shared_run,
    test_article_reprint_exclusion,
    test_article_reprint_image_fallback,
    test_article_originality_retry,
    test_article_jargon_leak,
    test_article_language_note,
    test_article_mentioned_sources,
    test_article_fetch_failure_gap,
    test_article_source_facts,
    test_article_draft_investigation,
    test_article_no_min_facts_gate,
    test_article_grading_tiers,
)
from tests.test_youtube import (
    test_measure_channels,
    test_actions_block_script,
    test_proxy_config,
    test_youtube_collect,
    test_youtube_extract,
    test_youtube_data_repo_paths,
    test_youtube_cluster,
    test_youtube_article,
    test_youtube_publish,
)


def main() -> int:
    install_fakes()
    print("\n── ترميز العناوين والتشابه ──")
    test_tokens_and_similarity()
    print("\n── الجلب والترشيح والترتيب ──")
    test_fetch_and_filter()
    print("\n── استخراج نصوص المقالات ──")
    test_extraction()
    print("\n── تأصيل التحليل ──")
    test_analysis_grounding()
    test_analysis_cleaning()
    test_cluster_members()
    print("\n── المحتوى النافع ──")
    test_useful_bucket()
    print("\n── ضوابط المحتوى الصحي ──")
    test_health_guardrails()
    print("\n── حصص التصنيفات ──")
    test_bucket_quotas()
    print("\n── الضوابط التحريرية ──")
    test_editorial_guardrails()
    print("\n── سرعة الانتشار ──")
    test_velocity()
    test_velocity_in_ranking()
    print("\n── المتابعات ──")
    test_followups()
    test_find_previous_prefers_posted_over_offered()
    print("\n── ذاكرة منع التكرار ──")
    test_dedupe_memory()
    test_dedupe_threshold_separation()
    print("\n── تدهور آمن عند غياب مفتاح API ──")
    test_screen_merge_missing_api_key()
    print("\n── عوامل الجذب التحريرية الثلاثة (Issue #876) ──")
    test_appeal_factors()
    print("\n── عوامل الجذب تؤثر في الترتيب الفعلي (Issue #881) ──")
    test_appeal_factors_affect_ranking()
    print("\n── كاشف تكرار النشر التلقائي (الرادار) ──")
    test_radar_gate_check_dedupe()
    test_radar_preselect_fallback()
    test_radar_auto_publish_builds_card()
    print("\n── ترشيح الصور ──")
    test_image_filtering()
    test_image_report()
    print("\n── الملصق الثاني على البطاقة (cards:) ──")
    test_card_second_badge_by_origin()
    print("\n── فكّ روابط Google News الوسيطة ──")
    test_google_news_link_decode()
    print("\n── إشارة Google Trends ──")
    test_trends()
    print("\n── وسم الإعلام الرسمي ──")
    test_state_media()
    print("\n── النص العربي والصور ──")
    test_arabic_shaping()
    print("\n── الأنبوب الكامل ──")
    test_collect_end_to_end()
    print("\n── دورة المراجعة ──")
    test_review_roundtrip()
    print("\n── نقطة التوقف قبل الصياغة (preselect) ──")
    test_preselect_no_spend_before_selection()
    test_preselect_no_duplicate_across_runs()
    test_preselect_finalize()
    test_preselect_now_builds_card_before_publish()
    test_preselect_now_card_build_failure_keeps_pending()
    test_preselect_empty_selection_no_spend()
    test_preselect_drops_stale_candidates()
    print("\n── مربعان لكل مرشح + ترجمة العناوين (Issue #319) ──")
    test_preselect_two_boxes_now_and_draft_review()
    test_preselect_draft_review_image_swap_works()
    test_preselect_card_marker_and_selected_card_ids()
    test_preselect_card_only_and_three_way_conflicts()
    test_preselect_card_build_failure_keeps_pending()
    test_preselect_translate_titles()
    test_finalize_format_mismatch_no_silent_fail()
    test_publish_conflicting_labels_no_dispatch()
    print("\n── عطل خارجي عند الصياغة مقابل رفض تحريري (preselect) ──")
    test_writer_classifies_write_errors()
    test_finalize_external_failure_keeps_approved_no_feedback()
    test_finalize_editorial_rejection_removes_approved()
    test_publish_pending_selection_single_dispatch()
    print("\n── الرابط في التعليق الأول ──")
    test_manual_image()
    test_editable_caption_and_image_source()
    test_setimage_revives_failed_draft_only_when_image_was_the_cause()
    test_request_search()
    print("\n── عناوين مقترحة مشتركة لمسارات الأخبار/الطلب/التحقق/المقال (Issue #756) ──")
    test_headlines_module()
    test_request_and_radar_headlines()
    test_headlines_failure_keeps_draft_with_empty_list()
    print("\n── التحقق من مقال ملصق ──")
    test_verify()
    print("\n── صياغة مسودة من المؤكَّد وحده (التحقق، المرحلة 2) ──")
    test_verify_draft()
    print("\n── فحص الأصالة: إعفاءا تكرار المصدر ووثيقة أخرى مقروءة ──")
    test_check_originality_signals()
    print("\n── فحص الأصالة: تقليم حدّي بقيد نحوي قبل الرفض ──")
    test_check_originality_trim()
    print("\n── فحص الأصالة: تجريد «الـ»، حد التقليم الأدنى، والجملة الكاملة عند الرفض ──")
    test_check_originality_context()
    print("\n── فحص الأصالة: إرجاع min_core إلى 5 + فجوة ضمائر «وهو» ──")
    test_check_originality_wa_pronoun_and_min_core_revert()
    test_check_originality_quantity()
    print("\n── فحص الأصالة: نواة ربط تسمية (تعليق الموافقة السادس عشر) ──")
    test_check_originality_name_link()
    print("\n── فحص الأصالة: الإعفاء الرابع — واقعة مسندة أُعطيت للكاتب ──")
    test_check_originality_grounded()
    print("\n── فحص الأصالة: القيمة الرابعة offending لمحاولة صياغة ثانية ──")
    test_check_originality_offending()
    print("\n── محرك البحث والقراءة المشترك (evidence.py) ──")
    test_evidence()
    print("\n── مقال من المصادر ──")
    test_article()
    test_article_statement_kind()
    test_article_merged_statement_gaps()
    test_article_statement_majority()
    test_article_split_statements()
    test_article_split_event_condition()
    test_article_mandatory_query_name()
    test_article_search_ladder()
    test_article_read_failure_substitution()
    test_article_wide_days()
    test_article_support_call_caching()
    test_article_source_fact_duplicate_index_on_topic()
    test_article_source_fact_topic_guard()
    test_article_source_fact_topic_guard_call_failure_admits()
    test_article_report_kind()
    test_article_generic_source_publisher()
    test_article_unsourced_entities()
    test_evidence_top_candidates()
    test_evidence_relevance_cap()
    test_evidence_relevance_display_matches_score()
    test_article_duplicate_query_reuse()
    test_article_longest_shared_run()
    test_article_reprint_exclusion()
    test_article_reprint_image_fallback()
    test_article_originality_retry()
    test_article_jargon_leak()
    test_article_language_note()
    test_article_mentioned_sources()
    test_article_fetch_failure_gap()
    test_article_source_facts()
    print("\n── منشور «تحقيق» من outcome._write_article (Issue #765) ──")
    test_article_draft_investigation()
    print("\n── إلغاء القاعدة 7: المقال لا يمتنع لقلة الوقائع (Issue #814 جزء 1) ──")
    test_article_no_min_facts_gate()
    test_article_grading_tiers()
    test_review_sibling_alternate_line()
    test_setimage_rebuild_card_uses_all_image_candidates()
    test_publish_investigation_requires_review()
    test_no_reject_boxes_in_review_issues()
    test_publish_unapproved_becomes_rejected()
    print("\n── مراجعة نهائية للبطاقة قبل النشر (Issue #858) ──")
    test_review_card_and_back_boxes()
    test_publish_card_request_defers_to_final_review()
    test_publish_final_review_approve_publishes_without_rebuild()
    test_publish_final_review_double_publish_guard()
    test_publish_final_review_back_request()
    test_publish_final_review_excludes_analysis_origin()
    test_first_comment()
    print("\n── نشر الدفعة بلا انتظار داخل مهمة urgent ──")
    test_burst_inline_cap_zero_defers_without_sleep()
    test_burst_urgent_still_immediate_with_inline_cap_zero()
    print("\n── الجدولة في أوقات الذروة ──")
    test_scheduling()
    test_due_publishes_one_at_a_time()
    print("\n── مسودة ناقصة لا تُسقط دفعة النشر أو فتح الـ Issue (Issue #707) ──")
    test_publish_skips_broken_draft_without_stopping_batch()
    test_burst_skips_broken_draft_without_spacing_sleep()
    test_open_review_excludes_youtube_and_broken_drafts()
    print("\n── ترتيب المرشحين والمسودات بالدرجة تنازليًا في العرض (Issue #874) ──")
    test_review_sort_by_score()
    test_open_review_orders_drafts_by_score()
    test_open_review_orders_candidates_by_score()
    test_publish_final_review_orders_by_score()
    test_collect_finalize_card_review_orders_by_score()
    print("\n── حقل origin المعياري وstore.origin_of (Issue #749) ──")
    test_origin_of_synonyms()
    test_feedback_records_origin_and_screening_guidance_excludes_analysis()
    test_feedback_screening_guidance_excludes_not_selected()
    test_radar_writes_breaking_origin()
    test_request_writes_request_origin()
    print("\n── التوجيه بالأصل لا بالوسم عند approved (Issue #740) ──")
    test_publish_routes_youtube_origin_by_field_not_label()
    test_publish_routes_news_origin_unaffected()
    test_publish_routes_mixed_origins_in_same_issue()
    test_publish_urgent_only_defers_youtube_to_normal_job()
    print("\n── سجل القرارات التراكمي (Issue #583، المرحلة الأولى) ──")
    test_decisions()
    print("\n── تحليل الأداء ──")
    test_insights_analysis()
    test_insights_collect_includes_analysis_origin()
    print("\n── تقرير الأداء: أضعف أداءً وقائمة المرفوضات (Issue #769) ──")
    test_insights_weakest_performing_section()
    test_insights_rejections_section()
    print("\n── تقرير الأداء: المقترحات كخيارات + الحلقة المغلقة (Issue #769) ──")
    test_insights_recommendation_ids_and_choice_parsing()
    test_insights_sync_does_not_refresh_unchanged_decision()
    test_insights_closed_loop()
    print("\n── تقرير الأداء: لماذا لم تنشر هذه؟ (Issue #843) ──")
    test_insights_why_not_published_section()
    test_insights_parse_reason_choices()
    test_insights_reason_choice_updates_rejection_and_feeds_screening()
    test_insights_why_entry_shown_twice_then_drops()
    test_insights_reason_entry_id_stable_despite_order()
    test_insights_why_section_missing_state_file()
    test_insights_no_posts_still_shows_why_and_decisions()
    print("\n── تحصين القرّاء الأربعة أمام مسودة تحليل بلا حقل image (Issue #749) ──")
    test_setimage_stores_manual_link_without_card()
    test_setimage_cli_sync_handles_cardless_draft()
    test_collect_feedback_rejects_analysis_draft_without_image()
    print("\n── setimage.apply_image يحافظ على وسم المسار (Issue #758) ──")
    test_setimage_apply_image_keeps_origin_badge()
    print("\n── اختيار عنوان غير افتراضي يعيد بناء البطاقة (Issue #760) ──")
    test_publish_builds_cards_at_approval()
    print("\n── حارس temperature (Issue #373) ──")
    test_no_temperature_param()
    print("\n── نسبة إصابة الذاكرة المؤقتة في تقرير الكلفة (طلب المراجعة) ──")
    test_writer_usage_summary_cache_ratio()
    print("\n── سكربت قياس قنوات يوتيوب (Issue #619) ──")
    test_measure_channels()
    print("\n── سكربت اختبار الحجب من Actions (Issue #626) ──")
    test_actions_block_script()
    print("\n── إعداد بروكسي Webshare (Issue #629) ──")
    test_proxy_config()
    print("\n── مسار يوتيوب: الجمع (Issue #631) ──")
    test_youtube_collect()
    print("\n── مسار يوتيوب: الاستخلاص (Issue #631) ──")
    test_youtube_extract()
    print("\n── مسار يوتيوب: مسارات مستودع البيانات الخاص (Issue #724) ──")
    test_youtube_data_repo_paths()
    print("\n── مسار يوتيوب: العنقدة (Issue #646) ──")
    test_youtube_cluster()
    print("\n── مسار يوتيوب: الكتابة (Issue #646) ──")
    test_youtube_article()
    print("\n── مسار يوتيوب: التوصيل (صورة + مسودة + مراجعة + نشر، Issue #676) ──")
    test_youtube_publish()

    print(f"\n{'═' * 50}\nنجح {len(PASSED)} · فشل {len(FAILED)}")
    if FAILED:
        print("الفاشل: " + "، ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
