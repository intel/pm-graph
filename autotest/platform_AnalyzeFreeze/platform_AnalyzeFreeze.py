# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os, commands, logging
from autotest_lib.client.bin import utils, test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import rtc, sys_power
import analyze_suspend as asusp

class platform_AnalyzeFreeze(test.test):
	version = 1
	def initialize(self):
		asusp.sysvals.suspendmode = 'freeze'
		if not asusp.statusCheck():
			logging.error('Status Check FAILED')
			raise error.TestFail('Status Check FAILED')
		asusp.sysvals.setPrecision(6)
		asusp.sysvals.mindevlen = 1
		asusp.sysvals.hostname = 'chromium'
		asusp.sysvals.initFtrace()
		asusp.sysvals.initTestOutput('.', self.resultsdir)
		logging.info('testdir    : %s' % asusp.sysvals.testdir)
		logging.info('dmesgfile  : %s' % asusp.sysvals.dmesgfile)
		logging.info('ftracefile : %s' % asusp.sysvals.ftracefile)
		logging.info('htmlfile   : %s' % asusp.sysvals.htmlfile)

	def run_once(self, devmode=False, waketime=15):
		if devmode and asusp.sysvals.usekprobes:
			asusp.sysvals.usedevsrc = True
		asusp.sysvals.rtcwake = True
		asusp.sysvals.rtcwaketime = waketime
		asusp.executeSuspend()
		asusp.sysvals.cleanupFtrace()
		logging.info('PROCESSING DATA')
		if(asusp.sysvals.usetraceeventsonly):
			# data for kernels 3.15 or newer is entirely in ftrace
			testruns = asusp.parseTraceLog()
		else:
			# data for kernels older than 3.15 is primarily in dmesg
			testruns = asusp.loadKernelLog()
			for data in testruns:
				asusp.parseKernelLog(data)
			if(asusp.sysvals.usecallgraph or asusp.sysvals.usetraceevents):
				asusp.appendIncompleteTraceLog(testruns)
		asusp.createHTML(testruns)
