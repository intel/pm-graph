#!/usr/bin/python
#
# Tool for generating a high level summary of a test output folder
# Copyright (c) 2013, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St - Fifth Floor, Boston, MA 02110-1301 USA.
#
# Authors:
#	 Todd Brandt <todd.e.brandt@intel.com>
#

import sys
import os
import re

def find_in_html(html, start, end, firstonly=True):
	n, out = 0, []
	while n < len(html):
		m = re.search(start, html[n:])
		if not m:
			break
		i = m.end()
		m = re.search(end, html[n+i:])
		if not m:
			break
		j = m.start()
		str = html[n+i:n+i+j]
		if end == 'ms':
			num = re.search(r'[-+]?\d*\.\d+|\d+', str)
			str = num.group() if num else 'NaN'
		if firstonly:
			return str
		out.append(str)
		n += i+j
	if firstonly:
		return ''
	return out

def printHelp():
	print("Generate a summary of a collection of multi-test runs")
	print("Usage: summaryx2 <folder>")
	return True

def doError(msg, help=False):
	print("ERROR: %s") % msg
	if(help == True):
		printHelp()
	sys.exit()

def info(file, data):
	html = open(file, 'r').read()
	line = find_in_html(html, '<div class="stamp">', '</div>')
	x = re.match('^(?P<host>.*) (?P<kernel>.*) (?P<mode>.*) \((?P<info>.*)\)', line)
	if not x:
		print 'WARNING: unrecognized formatting in summary file' % file
		return
	h, k, m, r = x.groups()
	if k not in data:
		data[k] = dict()
	if h not in data[k]:
		data[k][h] = dict()
	if m not in data[k][h]:
		data[k][h][m] = dict()
	smax = find_in_html(html, '<a href="#s%smax">' % m, '</a>')
	smed = find_in_html(html, '<a href="#s%smed">' % m, '</a>')
	smin = find_in_html(html, '<a href="#s%smin">' % m, '</a>')
	rmax = find_in_html(html, '<a href="#r%smax">' % m, '</a>')
	rmed = find_in_html(html, '<a href="#r%smed">' % m, '</a>')
	rmin = find_in_html(html, '<a href="#r%smin">' % m, '</a>')
	wres = dict()
	wsus = dict()
	for test in html.split('<tr'):
		if '<th>' in test or 'class="head"' in test or '<html>' in test:
			continue
		values = []
		out = test.split('<td')
		for i in out[1:]:
			values.append(i[1:].replace('</td>', '').replace('</tr>', '').strip())
		if values[9]:
			if values[9] not in wsus:
				wsus[values[9]] = 0
			wsus[values[9]] += 1
		if values[11]:
			if values[11] not in wres:
				wres[values[11]] = 0
			wres[values[11]] += 1
	wstext = '   Worst Suspend Devices:\n'
	for i in sorted(wsus, key=lambda k:wsus[k], reverse=True):
		wstext += '   - %s (%d times)\n' % (i, wsus[i])
	wrtext = '   Worst Resume Devices:\n'
	for i in sorted(wres, key=lambda k:wres[k], reverse=True):
		wrtext += '   - %s (%d times)\n' % (i, wres[i])
	data[k][h][m] = {
		'file': file,
		'results': '   %s' % r,
		'sstat': '   Suspend: %s, %s, %s' % (smax, smed, smin),
		'rstat': '   Resume : %s, %s, %s' % (rmax, rmed, rmin),
		'wsd': wstext[:-1],
		'wrd': wrtext[:-1],
	}

if __name__ == '__main__':
	if len(sys.argv) != 2:
		printHelp()
		sys.exit()

	dir = sys.argv[1]
	if not os.path.exists(dir) or not os.path.isdir(dir):
		doError('Folder not found')

	data = dict()
	for dirname, dirnames, filenames in os.walk(dir):
		for filename in filenames:
			if filename == 'summary.html':
				file = os.path.join(dirname, filename)
				info(file, data)

	message = ''
	for kernel in sorted(data):
		message += 'Sleepgraph stress test results for kernel %s (%d machines)\n' % \
			(kernel, len(data[kernel].keys()))
		for host in sorted(data[kernel]):
			message += '\n[%s]\n' % host
			for mode in sorted(data[kernel][host]):
				info = data[kernel][host][mode]
				message += '%s:\n' % mode.upper()
				message += '%s\n' % info['results']
				message += '%s\n' % info['sstat']
				message += '%s\n' % info['rstat']
				message += '%s\n' % info['wsd']
				message += '%s\n' % info['wrd']
	print message
