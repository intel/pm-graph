#!/usr/bin/python

import sys
import os
import re
import platform
from datetime import datetime, timedelta

class TestData:
	hostname = ''
	boottime = ''
	testtime = ''
	kernel = ''
	dmesgfile = ''
	outfile = ''
	dmesgtext = []
	valid = False
	initcall = False
	start = 0.0
	end = 0.0
	initstart = 0.0
	def __init__(self):
		self.testtime = datetime.now().strftime('%B %d %Y, %I:%M:%S %p')

def kernelVersion(msg):
	m = re.match('.* *(?P<k>[0-9]\.[0-9]{2}\.[0-9]-[a-z,0-9,\-+,_]*) .*', msg)
	if(m):
		return m.group('k')
	return ''

def getSysinfo(data):
	data.hostname = platform.node()
	fp = open('/proc/version', 'r')
	val = fp.read().strip()
	fp.close()
	data.kernel = kernelVersion(val)

def loadRawKernelLog(data):
	ktime = 0.0
	data.start = ktime

	if(data.dmesgfile):
		lf = open(data.dmesgfile, 'r')
	else:
		getSysinfo(data)
		lf = os.popen('dmesg')
	for line in lf:
		line = line.replace('\r\n', '')
		idx = line.find('[')
		if idx > 1:
			line = line[idx:]
		m = re.match('[ \t]*(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)', line)
		if(not m):
			continue
		val = m.group('ktime')
		try:
			ktime = float(val)
		except:
			continue
		msg = m.group('msg')
		if(ktime > 120 or re.match('PM: Syncing filesystems.*', msg)):
			break
		if(not data.valid):
			if(ktime == 0.0 and re.match('^Linux version .*', msg)):
				data.dmesgtext.append(line.strip())
				data.valid = True
				if(not data.kernel):
					data.kernel = kernelVersion(msg)
			continue
		if(not data.boottime):
			m = re.match('.* setting system clock to (?P<t>.*) UTC.*', msg)
			if(m):
				utc = int((datetime.now() - datetime.utcnow()).total_seconds())
				bt = datetime.strptime(m.group('t'), '%Y-%m-%d %H:%M:%S')
				bt = bt - timedelta(seconds=int(ktime)-utc)
				data.boottime = bt.strftime('%B %d %Y, %I:%M:%S %p')
		if(re.match('^calling *(?P<f>.*)\+.*', msg)):
			data.initcall = True
		elif(re.match('^initcall *(?P<f>.*)\+.*', msg)):
			data.initcall = True
		elif(re.match('^Freeing unused kernel memory.*', msg)):
			data.initstart = ktime
		else:
			continue
		data.dmesgtext.append(line.strip())
		data.end = ktime	

	lf.close()

def testResults(data):
	if(data.outfile):
		fp = open(data.outfile, 'w')
		for line in data.dmesgtext:
			fp.write(line+'\n')
		fp.close()
	print('          Host: %s' % data.hostname)
	print('     Test time: %s' % data.testtime)
	print('     Boot time: %s' % data.boottime)
	print('Kernel Version: %s' % data.kernel)
	print('         Valid: %s' % data.valid)
	if(not data.valid):
		return
	print('      Initcall: %s' % data.initcall)
	if(not data.initcall):
		return
	print('  Kernel start: %f' % data.start)
	print('    init start: %f' % data.initstart)
	print('      Data end: %f' % data.end)

def doError(msg, help):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit()

def printHelp():
	print('Usage: boottest <options>')
	print('Description:')
	print('  This tool reads in a dmesg log of linux kernel boot and')
	print('  creates tests whether a boot timeline can be made from it')
	print('Options:')
	print('  -h                 Print this help text')
	print('  -dmesg dmesgfile   read from file instead of dmesg')
	print('  -out file          output the data to file')

if __name__ == '__main__':
	data = TestData()
	args = iter(sys.argv[1:])
	for arg in args:
		if(arg == '-h'):
			printHelp()
			sys.exit()
		elif(arg == '-dmesg'):
			try:
				val = args.next()
			except:
				doError('No dmesg file supplied', True)
			data.dmesgfile = val
			if(os.path.exists(data.dmesgfile) == False):
				doError('%s doesnt exist' % data.dmesgfile, False)
		elif(arg == '-out'):
			try:
				val = args.next()
			except:
				doError('No outfile supplied', True)
			data.outfile = val
		else:
			doError('Invalid argument: '+arg, True)

	loadRawKernelLog(data)
	testResults(data)
