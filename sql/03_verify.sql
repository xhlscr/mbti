-- ============================================================================
-- 03_verify.sql · 导入后自检
-- 期望：题 80 / 每维 20 / 版本 1 条 published / 名人 64
-- ============================================================================

\echo '== 表数量（应为 8）'
SELECT count(*) AS tables
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('question_bank','bank_version','question','test_session',
                     'answer','result','celebrity','result_celebrity');

\echo '== 题库版本'
SELECT b.slug, v.version, v.status, v.question_count, v.content_hash
FROM question_bank b JOIN bank_version v ON v.id = b.current_version_id;

\echo '== 题目总数与维度分布'
SELECT dim, count(*) AS n FROM question GROUP BY dim ORDER BY dim;

\echo '== 选项数是否都是 5'
SELECT count(*) FILTER (WHERE jsonb_array_length(payload->'options') = 5) AS ok_5_options,
       count(*) AS total
FROM question;

\echo '== 题型分布'
SELECT type, count(*) FROM question GROUP BY type;

\echo '== 名人覆盖（16 型 × 每型人数）'
SELECT type, count(*) AS n FROM celebrity GROUP BY type ORDER BY type;

\echo '== 抽样一题'
SELECT code, dim, stem, payload->'options'->>0 AS option_a, tags
FROM question ORDER BY id LIMIT 1;
