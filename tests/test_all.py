#!/usr/bin/env python
# Python 2.5 features
from __future__ import with_statement

import sys
import os

from tempfile import mkdtemp
from shutil import rmtree

import unittest
from ..tool.main import main_real

def dispersyTest(callable_):
    """
    Decorator that calls the test named like the method name from dispersy.script.*
    """
    assert(callable_.__name__.startswith('test'))
    name = callable_.__name__[4:]
    script='Tribler.dispersy.script.%s' % name
    def caller(self):
        sys.argv = ['', '--script', script, '--statedir', mkdtemp(suffix=name, dir=os.path.join('tmp','dispersy_tests'))]
        callback = main_real()
        if callback.exception:
            raise type(callback.exception), callback.exception, callback.exception_traceback
    caller.__name__ = callable_.__name__
    return caller

class TestDispersyBatch(unittest.TestCase):
    def __init__(self, methodname='runTest'):
        unittest.TestCase.__init__(self, methodname)

    def setUp(self):
        os.chdir(sys.path[0])
        os.makedirs(os.path.join('tmp','dispersy_tests'))
        assert(os.path.exists('Tribler'))

    def tearDown(self):
        try:
            rmtree(os.path.join('tmp','dispersy_tests'))
        except:
            pass

    @dispersyTest
    def testDispersyBatchScript(self):
        pass
    @dispersyTest
    def testDispersyBootstrapServers(self):
        pass

    @dispersyTest
    def testDispersyClassificationScript(self):
        pass

    @dispersyTest
    def testDispersyCryptoScript(self):
        pass

    @dispersyTest
    def testDispersyDestroyCommunityScript(self):
        pass
    @dispersyTest
    def testDispersyDynamicSettings(self):
        pass
    @dispersyTest
    def testDispersyIdenticalPayloadScript(self):
        pass

    @dispersyTest
    def testDispersyMemberTagScript(self):
        pass

    @dispersyTest
    def testDispersyMissingMessageScript(self):
        pass

    @dispersyTest
    def testDispersySignatureScript(self):
        pass

    @dispersyTest
    def testDispersySyncScript(self):
        pass

    @dispersyTest
    def testDispersyTimelineScript(self):
        pass

    @dispersyTest
    def testDispersyUndoScript(self):
        pass
"""
"""
