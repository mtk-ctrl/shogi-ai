"""Regression: overflow must stay visible and selection must be resumable."""
import unittest
from tools.research.postgame_followup import select_batch


class BoundedFollowupQueueTest(unittest.TestCase):
    @staticmethod
    def tasks(count, unsupported=None):
        unsupported=set(unsupported or [])
        return [(dict(task_id=f'task-{i:03d}',
                      kind='inspect_evaluation_representation' if i in unsupported else 'extend_own_analysis',
                      priority=4), dict(evidence=i)) for i in range(count)]

    def test_eight_and_nine_do_not_fail_or_discard(self):
        for count in (8, 9, 96):
            batch, previous, pending, unsupported=select_batch(self.tasks(count), ())
            self.assertEqual(len(batch), min(8, count))
            self.assertEqual(len(pending), count-min(8, count))
            self.assertEqual(previous, [])
            self.assertEqual(unsupported, [])
            self.assertEqual(len(set([t['task_id'] for t,r in batch]+pending)), count)

    def test_completed_ids_are_skipped_without_repeating(self):
        all_tasks=self.tasks(19)
        one, previous, pending, unsupported=select_batch(all_tasks, ())
        completed=[t['task_id'] for t,r in one]
        two, earlier, remaining, unsupported=select_batch(all_tasks, completed)
        self.assertEqual(earlier, completed)
        self.assertEqual(len(two), 8)
        self.assertEqual(len(remaining), 3)
        self.assertFalse(set(completed)&set(t['task_id'] for t,r in two))
        self.assertEqual(len(set(earlier + [t['task_id'] for t,r in two] + remaining)), 19)

    def test_unsupported_is_preserved_not_transformed(self):
        batch, previous, pending, unsupported=select_batch(self.tasks(12, {0, 3}), ())
        self.assertEqual(unsupported, ['task-000', 'task-003'])
        self.assertEqual(len(batch), 8)
        self.assertEqual(len(pending), 2)
        self.assertNotIn('task-000', [t['task_id'] for t,r in batch])

    def test_rejects_forged_completion_and_bad_caps(self):
        with self.assertRaises(ValueError): select_batch(self.tasks(3), ['task-xyz'])
        with self.assertRaises(ValueError): select_batch(self.tasks(3), ['task-000', 'task-000'])
        with self.assertRaises(ValueError): select_batch(self.tasks(3), [], limit=9)

if __name__ == '__main__':
    unittest.main()
