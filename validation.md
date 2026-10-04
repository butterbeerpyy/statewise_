# Validation

The revised anonymous source passed 198 unit tests and all seven scripted fake cases. The scripted gate skips 257 live-only cases; this is not a live-model benchmark result. No live API requests were made during this validation.

The two reported failures were reproduced against the saved original baseline builder and corrected against the revised builder. Generic clarification changed from REFUSED to COMPLETE after a transient answer, with one interaction, no safety violation, and unchanged persistent memory. The correct-memory environment case changed from refusal for an unreliable state binding to successful execution. The StateWise untrusted-binding guard has the same source bytes as before this review.

Regression checks cover baseline independence from StateWise binding gates, explicit action target preservation, malformed-action refusal, intrinsic hard-policy refusal, baseline file fingerprints, true method-freeze rejection, and bounded API wait behavior. The source workspace's existing historical method freeze manifests were not overwritten. The anonymous release freeze manifests identify this repackaging, not historical experimental bytes.

Selected historical paper anchors also pass the supplied verify_paper_artifacts.py checks. Workbooks preserve all numeric cell values. Original hashes match all eight inputs in the recovered adjacent-version table manifest. Historical audit bundles retain failure outcomes and retry records.

Affected baseline empirical comparisons have not been rerun with the corrected code. Historical measurement records omit the baseline builder's hash, and some historical source versions are unavailable. Passing source tests does not resolve those paper-level limitations. See data_availability_review.md and historical_source_coverage.json.
