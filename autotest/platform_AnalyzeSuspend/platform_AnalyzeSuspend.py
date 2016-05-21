# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os, commands, logging
from autotest_lib.client.bin import utils, test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import rtc, sys_power
import analyze_suspend as asusp

class platform_AnalyzeSuspend(test.test):
	version = 1
	def initialize(self):
		asusp.sysvals.suspendmode = 'mem'
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

	def executeSuspend(self, waketime):
		if(asusp.sysvals.usecallgraph or asusp.sysvals.usetraceevents):
			ftrace = True
		else:
			ftrace = False
		fwdata = []
		asusp.sysvals.initdmesg()
		logging.info('START TRACING')
		if ftrace:
			asusp.sysvals.fsetVal('1', 'tracing_on')
			asusp.sysvals.fsetVal('SUSPEND START', 'trace_marker')
		sys_power.do_suspend(waketime)
		logging.info('RESUME COMPLETE')
		if ftrace:
			asusp.sysvals.fsetVal('RESUME COMPLETE', 'trace_marker')
			asusp.sysvals.fsetVal('0', 'tracing_on')
		fwdata.append(asusp.getFPDT(False))
		if ftrace:
			logging.info('CAPTURING TRACE')
			asusp.writeDatafileHeader(asusp.sysvals.ftracefile, fwdata)
			os.system('cat '+asusp.sysvals.tpath+'trace >> '+asusp.sysvals.ftracefile)
			asusp.sysvals.fsetVal('', 'trace')
			asusp.devProps()
		logging.info('CAPTURING DMESG')
		asusp.writeDatafileHeader(asusp.sysvals.dmesgfile, fwdata)
		asusp.sysvals.getdmesg()

	def run_once(self, devmode=False, waketime=15, power_manager=False):
		if devmode and asusp.sysvals.usekprobes:
			asusp.sysvals.usedevsrc = True
		if power_manager:
			self.executeSuspend(waketime)
		else:
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
