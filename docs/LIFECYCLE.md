# Lifecycle matrix (gate G7)

Every entity this product stores, against every way it can end or change under
something that already points at it. **A cell is a test, or a reason there is
nothing to test.** The audit's G7 class — "entity lifecycle edges nobody
enumerated" — is eight findings that all look the same from a distance: one
surface kept working from a row another surface had moved on from.

`scripts/check-lifecycle.py` (in `scripts/checkpoints.sh`) reads this file and
fails when a cited test no longer exists, when a cell is empty, or when the owed
list grows. **An entity or a state added without a row here fails the gate** —
`/integration-check` and `ship` P5 both require this file to be updated.

Cell vocabulary:

- `path::name` — the test that proves it. Python: `tests/x.py::test_y`. Web:
  `web/src/.../x.test.tsx::the it() title`. The checker asserts the file exists
  and still contains that name.
- `n/a — reason` — this edge cannot happen, and the reason says why.
- `owed → Snn` — no test today; `Snn` is the session that closes it. The list
  only shrinks: a new owed cell fails the gate.

| Entity | create | edit-after-use | archive | delete | expire | owner-removed | org-deleted |
|---|---|---|---|---|---|---|---|
| question | tests/test_api.py::test_create_question | owed → S14 | tests/test_api.py::test_archive_hides_from_list_but_keeps_reachable | tests/test_api.py::test_delete_question_with_submissions_409 | n/a — a question has no expiry; the invite carries it | tests/test_account_lifecycle.py::test_delete_account_purges_owned_data_only | tests/test_organizations.py::test_an_account_that_changed_organisations_can_still_be_deleted |
| assessment | tests/test_assessments.py::test_create_assessment_without_id_generates_slug | tests/test_assessments.py::test_update_locks_question_set_once_invited | tests/test_assessments.py::test_assessment_crud_roundtrip | tests/test_assessments.py::test_delete_blocked_by_invite | n/a — an assessment has no expiry | owed → S06 | owed → S06 |
| variant set | tests/test_variant_sets.py::test_variant_set_invites_round_robin | tests/test_slice_vs2.py::test_each_candidate_gets_a_different_variant_round_robin | owed → S14 | owed → S14 | n/a — no expiry of its own | owed → S06 | owed → S06 |
| invite | tests/test_slice1.py::test_invite_probe_reveals_no_question | tests/test_timer.py::test_editing_an_assessment_duration_does_not_move_a_live_deadline | n/a — an invite is revoked, not archived | tests/test_api.py::test_delete_question_cascades_invites | tests/test_invite_expiry.py::test_expired_link_cannot_start_a_sitting | tests/test_organizations.py::test_a_removed_member_keeps_their_account_and_can_start_again | owed → S06 |
| sitting | tests/test_timer.py::test_timed_start_returns_stable_deadline | tests/test_timer.py::test_editing_a_quick_screen_question_duration_does_not_move_a_live_deadline | n/a — a sitting is never archived; its submission is the record | tests/test_privacy.py::test_an_erased_candidate_can_no_longer_use_the_old_link | tests/test_invite_expiry.py::test_expiry_does_not_strand_a_sitting_already_started | owed → S20 | tests/test_privacy.py::test_every_interviewer_surface_reports_the_sitting_as_erased |
| member | tests/test_organizations.py::test_an_existing_account_can_accept_an_invitation | n/a — a membership's only mutable field is its role, whose edges are the delete cell | n/a — a membership is removed, not archived | tests/test_organizations.py::test_the_last_admin_cannot_be_demoted_or_removed | tests/test_organizations.py::test_an_expired_invitation_is_refused | tests/test_organizations.py::test_a_removed_member_keeps_their_account_and_can_start_again | owed → S06 |
| organisation | tests/test_organizations.py::test_register_founds_an_organisation_with_the_caller_as_admin | owed → S06 | n/a — an organisation is deleted, not archived | tests/test_organizations.py::test_the_only_admin_cannot_delete_their_way_out_of_a_team | n/a — an organisation does not expire; its plan lapses (see plan) | tests/test_account_lifecycle.py::test_delete_account_purges_owned_data_only | owed → S06 |
| candidate token | tests/test_slice1.py::test_invite_probe_reveals_no_question | n/a — the token is immutable; the invite behind it changes | n/a — no archive state | tests/test_slice2.py::test_revoke_invite_blocks_candidate | tests/test_invite_expiry.py::test_probe_shows_the_expiry_instead_of_dying_on_it | n/a — the token belongs to the organisation, not its author | owed → S06 |
| plan / subscription | tests/test_billing.py::test_a_new_organisation_is_on_the_free_plan_with_nothing_used | tests/test_billing.py::test_last_month_over_the_allowance_is_deducted_from_this_one | n/a — no archive state | n/a — a subscription is cancelled at Stripe, never deleted here | tests/test_billing.py::test_a_lapsed_subscription_falls_back_to_free_limits | n/a — the plan belongs to the organisation | owed → S06 |

## What this session added

**S05** filled the invite and sitting rows' `expire` and `edit-after-use` cells,
which is what the plan asked for: expiry is a start deadline once an attempt
exists (R2-004), and the sitting's length is frozen on the invite that was sent
(R2-031). The two cells sit next to each other on purpose — they are the two
ways a sitting's clock used to be decided by a row the candidate never saw.

## What the owed cells mean

They are not "untested code"; they are edges nobody has enumerated, which is
precisely how the eight G7 findings survived. Each names the session that owes
it, and that session deletes its entry in the same commit that adds the test.
