import copy
import unittest

import shogi
from tools.research.postgame_progress import POLICY_PROGRESS, describe, record, statistics, diagnosis_detail
from tools.research.postgame_spiral import prepare
from tools.research.postgame_ranker import BASE, OPTIONS, digest
from tools.research.postgame_runtime import initialize, advance
from tests.test_postgame_spiral import diagnosis
from tests.test_postgame_ranker import terms
from tests.test_postgame_runtime import FakeBackend, plan, drive, pub


PARENT = dict(engine_ref='a'*40, knowledge_sha256='b'*64,
              parameters_sha256=digest(dict(zip(OPTIONS, BASE))))


def measured(route='hold', split='train', context=None, static_error=False):
    row = diagnosis(); row['route'] = route
    root = copy.deepcopy(row['root_deep']); root['bestmove'] = row['case']['actual_move']
    def static(sfen):
        board = shogi.Board(sfen)
        research = board.piece_at(shogi.SQUARE_NAMES.index('2f')) is not None
        return terms(safety=(0 if research else 100) if static_error else (100 if research else 0))
    # Freeze a seed producing the requested grouping, before examining labels.
    for i in range(100):
        result = prepare([row], lambda _: [root, root], static, str(i),
                         parent_context=context or PARENT, parent_options=dict(zip(OPTIONS, BASE)),
                         track_decisions=True)
        if result['case_decisions'][0]['split'] == split:
            break
    else:
        raise AssertionError('fixture grouping unavailable')
    summary = dict(source_games=2, source_plies=200, selected_cases=1,
                   routes=result['routes'], verification_pairs=1, seconds=1.)
    result['progress'] = describe(result, summary, [row], context or PARENT)
    return result


def state(generation=1, previous=None):
    value = dict(plan=dict(cycle_id='synthetic-progress', progress_policy=POLICY_PROGRESS),
                 generation=generation, parent=PARENT)
    if previous:
        value.update(progress_history=previous['history'], research_followup=previous)
    return value


class ProgressTest(unittest.TestCase):
    def test_observed_rate_has_correct_denominator_and_no_strength_claim(self):
        r = measured(); p = r['progress']; s = p['statistics']
        self.assertEqual((s['selected_cases'], s['new_evaluation_pairs'], s['source_games']), (1, 0, 2))
        self.assertEqual(s['observed_selected_yield'], 0)
        self.assertEqual(s['deficits'], dict(pairs=32, train=8, validation=4, heldout=4))
        self.assertFalse(p['strength_improvement_demonstrated'])
        self.assertEqual(p['task_counts'], {'extend_own_analysis': 1})

    def test_two_unchanged_batches_pause_instead_of_blind_third_collection(self):
        first = record(state(), measured())
        self.assertFalse(first['halt_collection'])
        second = record(state(2, first), measured())
        self.assertTrue(second['halt_collection'])
        self.assertEqual(second['reason'], 'data_deficits_stagnant')
        self.assertEqual(second['history'][-1]['stagnant_preparations'], 2)

    def test_search_problem_can_request_memory_without_evaluation_pair(self):
        r = measured('stable_research_move_candidate')
        self.assertEqual(r['rejected']['no_static_rank_error_search_problem'], 1)
        self.assertEqual(len(r['examples']), 0)
        task = r['progress']['work_items'][0]
        self.assertEqual(task['kind'], 'validate_research_knowledge')
        self.assertEqual(task['case']['history_key'], diagnosis()['case']['history_key'])
        self.assertFalse(task['executor_connected'])
        self.assertEqual(record(state(), r)['reason'], 'knowledge_executor_not_connected')

    def test_validation_and_heldout_cannot_feed_practice_or_memory_queue(self):
        for split in ('validation', 'heldout'):
            r = measured('stable_research_move_candidate', split)
            self.assertEqual(r['progress']['work_items'], [])
            self.assertEqual(r['candidate_knowledge'], [])

    def test_wrong_analysis_and_changed_preparation_are_rejected(self):
        r = measured(); bad = copy.deepcopy(r['progress']['analysis']); bad['selected_cases'] += 1
        with self.assertRaises(ValueError): statistics(r, bad)
        r['case_decisions'][0]['reason'] = 'evaluation_eligible'
        with self.assertRaisesRegex(ValueError, 'different preparation'): record(state(), r)

    def test_forged_task_cannot_turn_a_test_group_into_training(self):
        r = measured(split='heldout'); training = measured()['progress']['work_items'][0]
        r['progress']['work_items'] = [training]
        r['progress']['task_counts'] = {'extend_own_analysis': 1}
        with self.assertRaisesRegex(ValueError, 'training decision'): record(state(), r)

    def test_small_progress_and_missing_time_are_not_invented(self):
        r = measured(); bare = {k:v for k,v in r.items() if k != 'progress'}
        summary = copy.deepcopy(r['progress']['analysis']); summary.pop('seconds')
        with self.assertRaises((KeyError, ValueError)): describe(bare, summary, [diagnosis()], PARENT)

    def test_solved_actual_moves_do_not_create_fake_research_tasks(self):
        r = measured('knowledge_reference_candidate')
        self.assertEqual(r['progress']['work_items'], [])
        self.assertEqual(r['progress']['statistics']['new_evaluation_pairs'], 0)

    def test_previous_research_tasks_are_carried_and_deduplicated(self):
        first = record(state(), measured())
        second = record(state(2, first), measured())
        self.assertEqual(len(second['work_items']), 1)
        self.assertEqual(second['work_items'], first['work_items'])

    def test_reduced_independent_data_deficit_resets_stagnation(self):
        first = record(state(), measured())
        second = record(state(2, first), measured('stable_research_move_candidate','validation',static_error=True))
        self.assertEqual(second['history'][-1]['stagnant_preparations'],0)
        self.assertTrue(second['history'][-1]['data_deficits_reduced'])
        self.assertFalse(second['halt_collection'])

    def test_actual_move_support_is_not_labelled_a_new_mistake(self):
        row=diagnosis();row['case']['actual_move']=row['research_move']
        self.assertEqual(diagnosis_detail(row),'actual_move_supported')
        row['root_short']['bestmove']='7g7f'
        self.assertEqual(diagnosis_detail(row),'actual_move_supported_with_search_disagreement')

    def test_missing_observations_and_mate_scales_have_separate_research(self):
        row=diagnosis();row['root_short']['status']='missing'
        self.assertEqual(diagnosis_detail(row),'short_observation_missing')
        row['root_deep']['kind']='mate'
        self.assertEqual(diagnosis_detail(row),'mate_requires_separate_verification')

    def test_small_margin_is_visible_without_being_promoted_to_a_teacher(self):
        row=diagnosis();row['followup']['comparison']['improvement_cp']=19
        self.assertEqual(diagnosis_detail(row),'improvement_below_150cp')


class MeasuredBackend(FakeBackend):
    def __init__(self, route='hold'):
        super().__init__(); self.route = route
    def prepare(self, env):
        return dict(preparation=measured(self.route), publication=pub(len(self.saved)))


class ProgressRuntimeTest(unittest.TestCase):
    def test_actual_controller_transition_stops_before_third_dispatch(self):
        p = plan(generations=3, budget=6); p['progress_policy'] = POLICY_PROGRESS
        b = MeasuredBackend(); e = drive(b, p)
        self.assertEqual([r['seed'] for r in b.launched], [1000,1100])
        self.assertEqual(e['state']['used_games'], 4)
        self.assertEqual(e['state']['result'], 'research_review_required')
        self.assertEqual(e['state']['research_followup']['reason'], 'data_deficits_stagnant')
        self.assertEqual(e['parent_options'], dict(zip(OPTIONS, BASE)))

    def test_knowledge_work_pauses_collection_instead_of_discarding_it(self):
        p = plan(generations=3, budget=6); p['progress_policy'] = POLICY_PROGRESS
        b = MeasuredBackend('stable_research_move_candidate'); e = drive(b, p)
        self.assertEqual(len(b.launched), 1)
        self.assertEqual(e['state']['research_followup']['next_action'], 'validate_research_knowledge')

    def test_new_policy_requires_measured_preparation_not_legacy_empty_report(self):
        p = plan(); p['progress_policy'] = POLICY_PROGRESS
        b = FakeBackend(); e = advance(initialize(p, dict(zip(OPTIONS,BASE)), 'c'*64), b)
        with self.assertRaises(KeyError): advance(e, b)
        self.assertEqual(len(b.launched), 1)

    def test_invalid_or_unbounded_policy_is_refused_before_any_dispatch(self):
        for policy in ({}, dict(POLICY_PROGRESS,max_stagnant_preparations=0),
                       dict(POLICY_PROGRESS,max_stagnant_preparations=6)):
            p=plan();p['progress_policy']=policy
            with self.assertRaises((KeyError,ValueError)):initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)


if __name__ == '__main__': unittest.main()
