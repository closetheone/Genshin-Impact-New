import unittest

from benchmark_boundaries import workload
from check_live_restrictions import run_case
from search_archive import ordered_passages
from validate_sample import project


class BoundaryTests(unittest.TestCase):
    def test_long_and_linked_fixture_contract(self):
        for profile in ('long', 'linked', 'deep', 'combined'):
            data, spec = workload(profile, 300)
            self.assertTrue(all(len(p['text']) == spec['characters'] for p in data['passages'][32:]))
            view = project(data, ['opening'])
            order = ordered_passages(view['passages'])
            self.assertEqual(len(order), len(view['passages']))
            self.assertTrue(all(set(p['next_ids']) <= {v['id'] for v in order} for p in order))
            if spec['fanout']:
                self.assertLess(len(view['passages']), len(data['passages']))
                self.assertNotEqual([p['id'] for p in order], [p['id'] for p in view['passages']])

    def test_wal_committed_restrictions_during_http_queries(self):
        for change in ('withdrawal', 'policy'):
            for purpose in ('display', 'export', 'external_ai'):
                with self.subTest(change=change, purpose=purpose):
                    self.assertTrue(run_case('WAL', change, purpose, readers=3)['all_checks_passed'])

    def test_default_journal_waits_then_enforces_restrictions(self):
        for change in ('withdrawal', 'policy'):
            with self.subTest(change=change):
                self.assertTrue(run_case('DELETE', change, 'display', readers=3)['writer_waited_for_readers'])

    def test_rolled_back_restrictions_do_not_invalidate_cursor(self):
        for journal in ('DELETE', 'WAL'):
            for change in ('withdrawal', 'policy'):
                with self.subTest(journal=journal, change=change):
                    result = run_case(journal, change, 'display', readers=3, rollback=True)
                    self.assertEqual(result['before_count'], result['after_count'])
                    self.assertEqual(result['old_cursor_http_status'], 200)


if __name__ == '__main__':
    unittest.main()
