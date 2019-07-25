#!/usr/bin/python2

import sys
import time
import os
import string
import re
from datetime import datetime
import base64
import json
import requests
import urllib

def webrequest(url):
	try:
		res = requests.get(url)
	except Exception as e:
		print('URL: %s\nException: %s' % (url, str(e)))
	if res == 0:
		print('ERROR: res == 0')
		return dict()
	res.raise_for_status()
	return res.json()

def bugs(urlprefix):
	params = {
		'bug_status'	: ['NEW','ASSIGNED','REOPENED','RESOLVED','VERIFIED','DEFERRED','NEEDINFO','CLOSED'],
		'op_sys'		: 'Linux',
#		'cf_tree'		: 'Mainline',
		'rep_platform'	: ['Intel','IA-32','IA-64'],
		'order'			: 'bugs.creation_ts desc',
#		'order'			: 'bugs.delta_ts desc',
#		'limit'			: '800',
	}
	url = '%s/bug?%s' % (urlprefix, urllib.urlencode(params, True))
	res = webrequest(url)
	if 'bugs' not in res:
		return []
	return res['bugs']

def attachments(urlprefix, id):
	url = '%s/bug/%s/attachment' % (urlprefix, id)
	res = webrequest(url)
	if 'bugs' not in res or id not in res['bugs']:
		return []
	return res['bugs'][id]

def parseMachineInfo(atts):
	out = []
	for att in atts:
		if 'data' not in att:
			continue
		data = base64.b64decode(att['data'])
		dmi = ''
		for line in data.split('\n'):
			m = re.match('.*\] DMI: (?P<info>.*)', line)
			if m:
				dmi = m.group('info').split(', BIOS')[0]
				if dmi and dmi not in out:
					out.append(dmi)
	return out

if __name__ == '__main__':

	machines = dict()
	urlprefix = 'http://bugzilla.kernel.org/rest.cgi'
	bugshow = ' - http://bugzilla.kernel.org/show_bug.cgi?id={0}  {1}'

	bugs = bugs(urlprefix)
	print '%d BUGS FOUND' % len(bugs)
	i = 0
	for bug in bugs:
		ctime = bug['creation_time']
		bugid = '%d' % bug['id']
		info = bugshow.format(bugid, ctime[:10])
		atts = attachments(urlprefix, bugid)
		print '%4d BUG: %sx%d %s' % (i, bugid, len(atts), ctime[:10])
		for m in parseMachineInfo(atts):
			if m not in machines:
				machines[m] = {'count':1,'bugs':[info]}
			else:
				machines[m]['count'] += 1
				machines[m]['bugs'].append(info)
			print 'MACHINE: %s, COUNT: %d' % (m, machines[m]['count'])
		i += 1

	print '\nTOTAL MACHINES: %d' % len(machines.keys())
	for m in sorted(machines, key=lambda k:machines[k]['count'], reverse=True):
		print 'MACHINE: %s, BUGS: %d' % (m, machines[m]['count'])
		for info in machines[m]['bugs']:
			print info
