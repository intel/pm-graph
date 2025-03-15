#!/usr/bin/env python3
import sys
import time
import string
import os
import argparse
from subprocess import call, Popen, PIPE

DATACACHE="~/.multitestdata"
TESTCACHE="~/.multitests"
ansi = False

def sanityCheck():
	global DATACACHE, TESTCACHE, ansi

	if 'HOME' in os.environ:
		DATACACHE = DATACACHE.replace('~', os.environ['HOME'])
		TESTCACHE = TESTCACHE.replace('~', os.environ['HOME'])

	if not os.path.exists(DATACACHE):
		print('ERROR: %s does not exist' % DATACACHE)
		sys.exit(1)

	if not os.path.exists(TESTCACHE):
		print('ERROR: %s does not exist' % TESTCACHE)
		sys.exit(1)

	if (hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()):
		ansi = True

def colorText(str, color=31):
	global ansi
	if not ansi:
		return str
	return '\x1B[1;%dm%s\x1B[m' % (color, str)

if __name__ == '__main__':

	parser = argparse.ArgumentParser()
	parser.add_argument('kernel1')
	parser.add_argument('kernel2')
	args = parser.parse_args()

	sanityCheck()

	print('Compare performance between [%s] and [%s]' %\
		(args.kernel1, args.kernel2))
	data = dict()
	fp = open(DATACACHE, 'r')
	for line in fp:
		vals = line.strip().split('|')
		kernel = vals[3]
		if kernel != args.kernel1 and kernel != args.kernel2:
			continue
		try:
			smed = float(vals[12])
			rmed = float(vals[15])
		except:
			continue
		mode = vals[4]
		host = vals[5]
		if host not in data:
			data[host] = dict()
		if mode not in data[host]:
			data[host][mode] = {'smed': -1, 'rmed': -1}
		if kernel not in data[host][mode]:
			data[host][mode][kernel] = {'smed': -1, 'rmed': -1}
		data[host][mode][kernel]['smed'] = smed
		data[host][mode][kernel]['rmed'] = rmed

	fullout = ''
	for host in sorted(data):
		hostgood = False
		out = '%s\n' % host
		for mode in sorted(data[host]):
			if args.kernel1 not in data[host][mode]:
				continue
			if args.kernel2 not in data[host][mode]:
				continue
			smed1 = data[host][mode][args.kernel1]['smed']
			rmed1 = data[host][mode][args.kernel1]['rmed']
			smed2 = data[host][mode][args.kernel2]['smed']
			rmed2 = data[host][mode][args.kernel2]['rmed']
			sdiff = smed2 - smed1
			rdiff = rmed2 - rmed1
			modeout = '%-6s: ' % mode
			list = []
			if abs(sdiff) > 40:
				c = 32 if sdiff < 0 else 31
				list.append(colorText('suspend %+.0f ms' % sdiff, c))
			if abs(rdiff) > 40:
				c = 32 if rdiff < 0 else 31
				list.append(colorText('resume %+.0f ms' % rdiff, c))
			if len(list) < 1:
				continue
			out += modeout + ', '.join(list) + '\n'
			hostgood = True
		if hostgood:
			fullout += out
	print(fullout)
