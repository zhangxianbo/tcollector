#!/usr/bin/python
# This file is part of tcollector.
# Copyright (C) 2013  The tcollector Authors.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details.  You should have received a copy
# of the GNU Lesser General Public License along with this program.  If not,
# see <http://www.gnu.org/licenses/>.

import os
import sys
from stat import S_ISDIR, S_ISREG, ST_MODE
import unittest

import mocks
import tcollector

PY3 = sys.version_info[0] > 2


def return_none(x):
    return None


def always_true():
    return True


class CollectorsTests(unittest.TestCase):

    def test_collectorsAccessRights(self):
        """Test of collectors access rights, permissions should be 0100775."""

        def check_access_rights(top):
            for f in os.listdir(top):
                pathname = os.path.join(top, f)
                mode = os.stat(pathname).st_mode

                if S_ISDIR(mode):
                    # directory, recurse into it
                    check_access_rights(pathname)
                elif S_ISREG(mode):
                    # file, check permissions
                    permissions = oct(os.stat(pathname)[ST_MODE])
                    if PY3:
                        self.assertEqual("0o100775", permissions)
                    else:
                        self.assertEqual("0100775", permissions)
                else:
                    # unknown file type
                    pass

        collectors_path = os.path.dirname(os.path.abspath(__file__)) + \
            "/collectors/0"
        check_access_rights(collectors_path)


class TSDBlacklistingTests(unittest.TestCase):
    """
    Tests of TSD blacklisting logic
    https://github.com/OpenTSDB/tcollector/commit/c191d0d0889860db2ea231cad02e398843031a74
    """

    def setUp(self):
        # Stub out the randomness
        self.random_shuffle = tcollector.random.shuffle # pylint: disable=maybe-no-member
        tcollector.random.shuffle = lambda x: x # pylint: disable=maybe-no-member

    def tearDown(self):
        tcollector.random.shuffle = self.random_shuffle # pylint: disable=maybe-no-member

    def mkSenderThread(self, tsds):
        return tcollector.SenderThread(None, True, tsds, False, {}, reconnectinterval=5) # pylint: disable=maybe-no-member

    def test_blacklistOneConnection(self):
        tsd = ("localhost", 4242)
        sender = self.mkSenderThread([tsd])
        sender.pick_connection()
        self.assertEqual(tsd, (sender.host, sender.port))
        sender.blacklist_connection()
        sender.pick_connection()
        self.assertEqual(tsd, (sender.host, sender.port))

    def test_blacklistTwoConnections(self):
        tsd1 = ("localhost", 4242)
        tsd2 = ("localhost", 4243)
        sender = self.mkSenderThread([tsd1, tsd2])
        sender.pick_connection()
        self.assertEqual(tsd1, (sender.host, sender.port))
        sender.blacklist_connection()
        sender.pick_connection()
        self.assertEqual(tsd2, (sender.host, sender.port))
        sender.blacklist_connection()
        sender.pick_connection()
        self.assertEqual(tsd1, (sender.host, sender.port))

    def test_doublePickOneConnection(self):
        tsd = ("localhost", 4242)
        sender = self.mkSenderThread([tsd])
        sender.pick_connection()
        self.assertEqual(tsd, (sender.host, sender.port))
        sender.pick_connection()
        self.assertEqual(tsd, (sender.host, sender.port))

    def test_doublePickTwoConnections(self):
        tsd1 = ("localhost", 4242)
        tsd2 = ("localhost", 4243)
        sender = self.mkSenderThread([tsd1, tsd2])
        sender.pick_connection()
        self.assertEqual(tsd1, (sender.host, sender.port))
        sender.pick_connection()
        self.assertEqual(tsd2, (sender.host, sender.port))
        sender.pick_connection()
        self.assertEqual(tsd1, (sender.host, sender.port))

class UDPCollectorTests(unittest.TestCase):

    def setUp(self):
        if ('udp_bridge.py' not in tcollector.COLLECTORS): # pylint: disable=maybe-no-member
            return

        self.saved_exit = sys.exit
        self.saved_stderr = sys.stderr
        self.saved_stdout = sys.stdout
        self.udp_bridge = tcollector.COLLECTORS['udp_bridge.py'] # pylint: disable=maybe-no-member
        self.udp_globals = {}

        sys.exit = return_none
        bridge_file = open(self.udp_bridge.filename)
        try:
            exec(compile(bridge_file.read(), self.udp_bridge.filename, 'exec'), self.udp_globals)
        finally:
            bridge_file.close()
            sys.exit = self.saved_exit

        self.udp_globals['socket'] = mocks.Socket()
        self.udp_globals['sys'] = mocks.Sys()
        self.udp_globals['udp_bridge_conf'].enabled = always_true
        self.udp_globals['utils'] = mocks.Utils()

    def run_bridge_test(self, udpInputLines, stdoutLines, stderrLines):
        mockSocket = self.udp_globals['socket'] = mocks.Socket()
        mockSocket.state['udp_in'] = list(udpInputLines)

        self.udp_globals['sys'] = mocks.Sys()
        self.udp_globals['sys'].stderr.lines = stderrLines
        self.udp_globals['sys'].stdout.lines = stdoutLines
        sys.stderr = self.udp_globals['sys'].stderr
        sys.stdout = self.udp_globals['sys'].stdout

        try:
            self.udp_globals['main']()
        except mocks.SocketDone:
            pass
        finally:
            sys.stderr = self.saved_stderr
            sys.stdout = self.saved_stdout

    def test_populated(self):
        # assertIsInstance, assertIn, assertIsNone do not exist in Python 2.6
        self.assertTrue(isinstance(self.udp_bridge, tcollector.Collector), msg="self.udp_bridge not instance of tcollector.Collector") # pylint: disable=maybe-no-member
        self.assertEqual(self.udp_bridge.proc, None)
        self.assertTrue('main' in self.udp_globals, msg="'main' not in self.udp_globals")

    def test_single_line_no_put(self):
        inputLines = [
            'foo.bar 1 1'
        ]
        expected = '\n'.join(inputLines) + '\n'
        stderr = []
        stdout = []
        self.run_bridge_test(inputLines, stdout, stderr)

        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_single_line_put(self):
        inputLines = [
            'put foo.bar 1 1'
        ]
        expected = '\n'.join([
            'foo.bar 1 1'
        ]) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_line_no_put(self):
        inputLines = [
            'foo.bar 1 1',
            'bar.baz 2 2'
        ]
        expected = '\n'.join(inputLines) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_line_put(self):
        inputLines = [
            'put foo.bar 1 1',
            'put bar.baz 2 2'
        ]
        expected = '\n'.join([
            'foo.bar 1 1',
            'bar.baz 2 2'
        ]) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_line_mixed_put(self):
        inputLines = [
            'put foo.bar 1 1',
            'bar.baz 2 2',
            'put foo.bar 3 3'
        ]
        expected = '\n'.join([
            'foo.bar 1 1',
            'bar.baz 2 2',
            'foo.bar 3 3'
        ]) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_line_no_put_cond(self):
        inputLines = [
            'foo.bar 1 1\nbar.baz 2 2'
        ]
        expected = '\n'.join(inputLines) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_line_put_cond(self):
        inputLines = [
            'put foo.bar 1 1\nput bar.baz 2 2'
        ]
        expected = '\n'.join([
            'foo.bar 1 1',
            'bar.baz 2 2'
        ]) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_empty_line_no_put(self):
        inputLines = [
            'foo.bar 1 1',
            '',
            'bar.baz 2 2'
        ]
        expected = 'foo.bar 1 1\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, ['invalid data\n'])

    def test_multi_empty_line_put(self):
        inputLines = [
            'put foo.bar 1 1',
            '',
            'put bar.baz 2 2'
        ]
        expected = 'foo.bar 1 1\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, ['invalid data\n'])

    def test_multi_empty_line_no_put_cond(self):
        inputLines = [
            'foo.bar 1 1\n\nbar.baz 2 2'
        ]
        expected = '\n'.join(inputLines) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

    def test_multi_empty_line_put_cond(self):
        inputLines = [
            'put foo.bar 1 1\n\nput bar.baz 2 2'
        ]
        expected = '\n'.join([
            'foo.bar 1 1',
            '',
            'bar.baz 2 2'
        ]) + '\n'
        stderr = []
        stdout = []

        self.run_bridge_test(inputLines, stdout, stderr)
        self.assertEqual(''.join(stdout), expected)
        self.assertEqual(stderr, [])

if __name__ == '__main__':
    cdir = os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])),
                        'collectors')
    tcollector.setup_python_path(cdir) # pylint: disable=maybe-no-member
    tcollector.populate_collectors(cdir) # pylint: disable=maybe-no-member
    sys.exit(unittest.main())
