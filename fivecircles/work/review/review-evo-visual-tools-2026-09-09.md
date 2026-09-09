# HOTLINE.VISUAL.2 self-review

2026-09-09T15:04:39+09:00. Scope: actual policy-selected visual search/inspection, not a replacement Controller.

Decision: APPROVE_WITH_LIMITS for the opt-in implementation, scoped tests and demonstrated live route. No independent-review or semantic-quality approval.

- Scope filter reaches the persisted vector index before ranking. All returned candidates are checked against loaded index citations and current hard scope; unknown/empty scope cannot become global.
- Model-selected inputs are query strings and current handles, never filesystem paths. Real image bytes are hash/locator checked; no OCR text is substituted for pixels.
- Existing policy backend/model/processor are reused. Image preparation/grammar/pixel proof/context cap and uncertainty validator remain the imported behavior.
- All work is under the original120-second owned supervisor, query child gets actual remaining time, image pre/post checks and shared budgets/counters are present. No standalone180-second child is attached to an Evo episode.
- Cache keys include action/query/scope/index/profile; unsuccessful providers do not mint cache successes. An uncertain image cannot be cited as a finish window.
- Text defaults are unchanged when capability is off. Mixed text/visual windows preserve per-source citations and visual_inference flags through answer composition and output. Original semantic_verified=false remains.
- Real execution exposed interpreter path loss and review-label confusion; fixes preserve guards and original failure records. Final378 unique tests passed and live003 selected all3 steps with no invalid action.
- Real final answer/citation output is not proof of text recognition correctness: single-image index and varying readouts are explicit limitations. Source data, weights, policy training and default UI are not altered.

Evidence: ../2026-09-09-evo-visual-tools.md and ignored diagnostics, final-source.sha256, final-combined logs, live003 result/supervisor.
