# Copyright (c) 2015 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import testtools

from shaker.engine import sla


class TestSla(testtools.TestCase):
    def test_eval(self):
        self.assertEqual(2 ** 6, sla.eval_expr('2**6'))
        self.assertEqual(True, sla.eval_expr('11 > a > 5', {'a': 7}))
        self.assertEqual(42, sla.eval_expr('2 + a.b', {'a': {'b': 40}}))
        self.assertEqual(True, sla.eval_expr('11 > 7 and 5 < 6'))
        self.assertEqual(False, sla.eval_expr('(not 11 > 7) or (not 5 < 6)'))

    def test_eval_regex(self):
        self.assertEqual(True, sla.eval_expr('"some text" & "\w+\s+\w+"'))
        self.assertEqual(False, sla.eval_expr('"some text" & "\d+"'))

    def test_eval_sla(self):
        records = [{'type': 'agent', 'test': 'iperf_tcp',
                    'stats': {'bandwidth': {'mean': 700}}},
                   {'type': 'agent', 'test': 'iperf_udp',
                    'stats': {'bandwidth': {'mean': 1000}}},
                   {'type': 'node', 'test': 'iperf_tcp',
                    'stats': {'bandwidth': {'mean': 850}}}]

        expr = 'stats.bandwidth.mean > 800'
        sla_records = sla.eval_expr('[type == "agent"] >> (%s)' % expr,
                                    records)
        self.assertEqual([
            sla.SLAItem(record=records[0], state=False, expression=expr),
            sla.SLAItem(record=records[1], state=True, expression=expr)],
            sla_records)

        expr = 'stats.bandwidth.mean > 900'
        sla_records = sla.eval_expr('[test == "iperf_udp", type == "node"] >> '
                                    '(%s)' % expr, records)
        self.assertEqual([
            sla.SLAItem(record=records[1], state=True, expression=expr),
            sla.SLAItem(record=records[2], state=False, expression=expr)],
            sla_records)

    def test_dump_ast_node(self):
        self.assertEqual('(stats.bandwidth.mean > 900)', sla.dump_ast_node(
            ast.parse('stats.bandwidth.mean > 900', mode='eval')))

        expr = ('(stats.bandwidth.mean > 900 and not stats.ping.max < 0.5 and '
                'stats.ping.mean < 0.35)')
        self.assertEqual(expr,
                         sla.dump_ast_node(ast.parse(expr, mode='eval')))
