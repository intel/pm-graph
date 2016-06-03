# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os, commands, logging
from autotest_lib.client.bin import utils, test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import rtc, sys_power
import analyze_boot as ab

class platform_AnalyzeBoot(test.test):
	version = 1
	myparams = [
		'initcall_debug',
		'log_buf_len='
	]
	dmesgfile = ''
	def initialize(self):
		# pass in the dmesg instead of getting it from popen(dmesg)
		self.dmesgfile = os.path.join(self.resultsdir, 'dmesg.txt')
		if not self.checkKernelParameters(self.myparams):
			self.testFail('Missing Kernel Parameters: %s' % self.myparams)
		# setup the test with the right command line params
		ab.sysvals.hostname = 'chromium'
		ab.sysvals.htmlfile = os.path.join(self.resultsdir, 'bootgraph.html')
		ab.sysvals.dmesgfile = self.dmesgfile
		logging.info('dmesgfile  : %s' % ab.sysvals.dmesgfile)
		logging.info('htmlfile   : %s' % ab.sysvals.htmlfile)

	def checkKernelParameters(self, myparams):
		try:
			fp = open('/proc/cmdline')
			cmdline = fp.read().strip()
			fp.close()
		except:
			return False
		for param in myparams:
			if param not in cmdline:
				return False
		return True

	def run_once(self):
		logging.info('Retrieve dmesg log from sysinfo')
		# copy the dmesg.gz log from the sysinfo to results
		dmesg = os.path.join(self.resultsdir, '../../sysinfo/dmesg.gz')
		os.system('cp %s %s' % (dmesg, self.resultsdir))
		# gunzup the file and create the input dmesg file
		dmesg = os.path.join(self.resultsdir, 'dmesg')
		os.system('gunzip %s.gz; mv %s %s' % (dmesg, dmesg, self.dmesgfile))
		# run the test, load the kernel log
		logging.info('Load the dmesg log')
		data = ab.loadRawKernelLog()
		# verify the file has enough data to actually get a timeline
		logging.info('Extract basic test info from the log')
		ab.testResults(data, False)
		if not data.valid:
			self.testFail('Data is invalid: the dmesg log was incomplete')
		# parse the log and create a timeline object
		logging.info('Parse the dmesg log and create a timeline')
		ab.parseKernelBootLog(data)
		# convert the timeline object into an html timeline
		logging.info('Generate the html timeline output')
		ab.createBootGraph(data, False)

	def testFail(self, errtext):
		logging.error(errtext)
		raise error.TestFail(errtext)
