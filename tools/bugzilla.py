#!/usr/bin/python

import sys
import base64
import time
import re
import json
import requests
import configparser
import pickle
from io import StringIO
try:
	from urllib import urlencode
except ImportError:
	from urllib.parse import urlencode

def webrequest(url, retry=0):
	try:
		res = requests.get(url)
		res.raise_for_status()
	except Exception as e:
		print('URL: %s\nERROR: %s' % (url, str(e)))
		if retry >= 5:
			sys.exit(1)
			return dict()
		print('RETRYING(%d) %s' % (retry+1, url))
		time.sleep(5)
		return webrequest(url, retry+1)
	return res.json()

def getissues(urlprefix, depissue):
	out = dict()
	params = {
#		'bug_status'	: ['NEW','ASSIGNED','REOPENED','VERIFIED','NEEDINFO','CLOSED'],
		'blocks'		: [depissue],
		'order'			: 'bugs.creation_ts desc',
	}
	url = '%s/bug?%s' % (urlprefix, urlencode(params, True))
	res = webrequest(url)
	if 'bugs' not in res:
		return out
	bugs = res['bugs']
	showurl = urlprefix.replace('rest', 'show_bug') + '?id={0}'
	for bug in bugs:
		id = '%d' % bug['id']
		url = '%s/bug/%s/attachment' % (urlprefix, id)
		res = webrequest(url)
		if 'bugs' not in res or id not in res['bugs']:
			continue
		idef = ''
		for att in res['bugs'][id]:
			if not att['is_obsolete'] and att['file_name'] == 'issue.def':
				idef = base64.b64decode(att['data'])
		if 'resolution' in bug and bug['resolution']:
			statinfo = '%s %s' % (bug['status'], bug['resolution'])
		else:
			statinfo = '%s' % (bug['status'])
		desc = '%s [%s]' % (bug['summary'], statinfo)
		out[id] = {
			'def': idef,
			'matches': 0,
			'worst': 0,
			'url': showurl.format(id),
			'desc': desc,
			'status': statinfo,
		}
	return out

def loadissue(file):
	out = dict()
	out['1'] = {
		'def': open(file, 'rb').read(),
		'matches': 0,
		'worst': 0,
		'url': '',
		'desc': 'custom issue',
		'status': 'UNKNOWN',
	}
	return out

def countFormat(count, total):
	p = 100*float(count)/float(total)
	return '%d / %d (%.2f%%)' % (count, total, p)

def regexmatch(mstr, line):
	if mstr in line or re.match(mstr, line):
		return True
	return False

def device_title_match(dev, namestr, devstr, drvstr):
	# get driver string if found
	name, devid, drv = '', dev, ''
	if ' {' in dev:
		m = re.match('^(?P<x>.*) \{(?P<y>\S*)\}$', dev)
		if m:
			devid, drv = m.groups()
	# get device id if found
	if ' [' in devid:
		m = re.match('^(?P<x>.*) \[(?P<y>\S*)\]$', devid)
		if m:
			name, devid = m.groups()
	if drvstr:
		if not drv or not regexmatch(drvstr, drv):
			return False
	if namestr:
		if not name or not regexmatch(namestr, name):
			return False
	if devstr:
		if not devid or not regexmatch(devstr, devid):
			return False
	return True

def check_issue(host, vals, issues, testruns, bugdata):
	for val in vals:
		for issue in issues:
			if host in issue['urls'] and regexmatch(val, issue['line']):
				bugdata['found'] = issue['urls'][host][0]
				bugdata['count'] = issue['tests']
				return True
	return False

def getComparison(mstr):
	greater = True
	if '>' in mstr:
		tmp = mstr.split('>')
	elif '<' in mstr:
		greater = False
		tmp = mstr.split('<')
	else:
		return ('', -1, greater)
	name = tmp[0].strip()
	try:
		target = float(tmp[-1].strip())
	except:
		return ('', -1, greater)
	return (name, target, greater)

def check_call_time(mstrs, testruns, bugdata):
	checks = []
	# gather items needed for match checks
	for mstr in mstrs:
		callstr, target, greater = getComparison(mstr)
		if not callstr or target < 0:
				continue
		name, args, tm = functionInfo(callstr)
		checks.append((name, args, target, greater))
	match = {'count':0,'worst':0,'url':''}
	for data in testruns:
		found = False
		for name, args, target, greater in checks:
			for f in data['funclist']:
				n, a, t = functionInfo(f)
				if not regexmatch(name, n):
					continue
				argmatch = True
				for arg in args:
					if arg not in a or not regexmatch(args[arg], a[arg]):
						argmatch = False
				if not argmatch or t < 0:
					continue
				# match found
				if (greater and t > target) or (not greater and t < target):
					if not match['url'] or \
						(greater and t > match['worst']) or \
						(not greater and t < match['worst']):
						# worst case found
						match['worst'] = t
						match['url'] = data['url']
					found = True
		if found:
			match['count'] += 1
	bugdata['found'] = match['url']
	bugdata['count'] = match['count']

def check_device_time(mstrs, testruns, bugdata):
	checks = []
	# gather items needed for match checks
	for phase, mstr in mstrs:
		devstr, target, greater = getComparison(mstr)
		if not devstr or target < 0:
			continue
		name, devid, drv = deviceInfo(devstr)
		checks.append((phase, name, devid, drv, target, greater))
	match = {'count':0,'worst':0,'url':''}
	for data in testruns:
		found = False
		for phase, name, devid, drv, target, greater in checks:
			if phase not in data['devlist']:
				continue
			for dev in data['devlist'][phase]:
				if not device_title_match(dev, name, devid, drv):
					continue
				val = data['devlist'][phase][dev]
				if (greater and val > target) or (not greater and val < target):
					# match found
					if not match['url'] or \
						(greater and val > match['worst']) or \
						(not greater and val < match['worst']):
						# worst case found
						match['worst'] = val
						match['url'] = data['url']
					found = True
		if found:
			match['count'] += 1
	bugdata['found'] = match['url']
	bugdata['count'] = match['count']

def functionInfo(text):
	# function time is at the end
	tm = -1
	if ')' in text:
		tmp = text.split(')')
		text = tmp[0]
		tstr = tmp[1].split('(')[-1]
		if re.match('[0-9\.]*ms', tstr):
			tm = float(tstr[:-2])
	# get the function name and args
	tmp = text.split('(')
	name, args = tmp[0], dict()
	if len(tmp) > 1:
		for arg in tmp[1].split(','):
			if '=' not in arg:
				continue
			atmp = arg.strip().split('=')
			args[atmp[0].strip()] = atmp[-1].strip()
	return (name, args, tm)

def find_function(mstr, testruns):
	name, args, tm = functionInfo(mstr)
	for data in testruns:
		for f in data['funclist']:
			n, a, t = functionInfo(f)
			if not regexmatch(name, n):
				continue
			argmatch = True
			for arg in args:
				if arg not in a or not regexmatch(args[arg], a[arg]):
					argmatch = False
			if argmatch:
				return True
	return False

def deviceInfo(text):
	name = devid = drv = ''
	for val in text.split(','):
		val = val.strip()
		if val.lower().startswith('name='):
			name = val[5:].strip()
		elif val.lower().startswith('driver='):
			drv = val[7:].strip()
		elif val.lower().startswith('device='):
			devid = val[7:].strip()
		else:
			devid = val
	return (name, devid, drv)

def find_device(mstr, testruns):
	name, devid, drv = deviceInfo(mstr)
	for data in testruns[:10]:
		for phase in data['devlist']:
			for dev in data['devlist'][phase]:
				if device_title_match(dev, name, devid, drv):
					return True
	return False

def bugzilla_check(buglist, desc, testruns, issues):
	out = []
	for id in buglist:
		if not buglist[id]['def']:
			continue
		# check each bug to see if it is applicable and exists
		applicable = True
		# parse the config file which describes the issue
		config = configparser.ConfigParser()
		if isinstance(buglist[id]['def'], str):
			data = buglist[id]['def']
		else:
			data = buglist[id]['def'].decode()
		config.readfp(StringIO(data))
		sections = config.sections()
		req = idesc = ''
		for key in sections:
			if key.lower() == 'requirements':
				req = key
			elif key.lower() == 'description':
				idesc = key
		# verify that this system & multitest meets the requirements
		if req:
			for key in config.options(req):
				val = config.get(req, key)
				if key.lower() == 'mode':
					applicable = (desc['mode'] in val)
				elif key.lower() == 'device':
					applicable = find_device(val, testruns)
				elif key.lower() == 'call':
					applicable = find_function(val, testruns)
				else:
					applicable = (val.lower() in desc['sysinfo'].lower())
				if not applicable:
					break
		if not applicable or not idesc:
			continue
		# check for the existence of the issue in the data
		bugdata = {
			'id': id,
			'desc': buglist[id]['desc'],
			'bugurl': buglist[id]['url'],
			'count': 0,
			'found': '',
		}
		checkI, checkD, checkC = [], [], []
		for key in config.options(idesc):
			val = config.get(idesc, key)
			if key.lower().startswith('dmesgregex'):
				checkI.append(val)
			elif key.lower() in ['devicesuspend', 'deviceresume']:
				checkD.append((key[6:].lower(), val))
			elif key.lower() == 'calltime':
				checkC.append(val)
		if not bugdata['found'] and len(checkI) > 0:
			check_issue(desc['host'], checkI, issues, testruns, bugdata)
		if not bugdata['found'] and len(checkD) > 0:
			check_device_time(checkD, testruns, bugdata)
		if not bugdata['found'] and len(checkC) > 0:
			check_call_time(checkC, testruns, bugdata)
		out.append(bugdata)
	return out

def html_table(testruns, bugs, desc):
	# generate the html
	th = '\t<th>{0}</th>\n'
	td = '\t<td align={0}>{1}</td>\n'
	tdlink = '<a href="{1}">{0}</a>'
	subtitle = '%d relevent bugs' % len(bugs) if len(bugs) != 1 else '1 relevent bug'
	html = '<br><div class="stamp">Bugzilla Tracking (%s)</div><table>\n' % (subtitle)
	html += '<tr>\n' +\
		th.format('Bugzilla') + th.format('Description') + th.format('Status') +\
		th.format('Kernel') + th.format('Mode') + th.format('Count') +\
		th.format('Fail Rate') + th.format('First Instance') + '</tr>\n'

	total, num = len(testruns), 0
	for bug in sorted(bugs, key=lambda v:v['count'], reverse=True):
		bugurl = tdlink.format(bug['id'], bug['bugurl'])
		if bug['found']:
			status = td.format('center nowrap style="color:#f00;"', 'ISSUE HAPPENED')
			timeline = tdlink.format(desc['host'], bug['found'])
		else:
			status = td.format('center nowrap style="color:#080;"', 'ISSUE NOT FOUND')
			timeline = ''
		rate = '%d/%d (%.2f%%)' % (bug['count'], total, 100*float(bug['count'])/float(total))
		# row classes - alternate row color
		rcls = ['alt'] if num % 2 == 1 else []
		html += '<tr class="'+(' '.join(rcls))+'">\n' if len(rcls) > 0 else '<tr>\n'
		html += td.format('center nowrap', bugurl)		# bug id/url
		html += td.format('left nowrap', bug['desc'])	# bug desc
		html += status									# bug status
		html += td.format('center', desc['kernel'])		# kernel
		html += td.format('center', desc['mode'])		# mode
		html += td.format('center', bug['count'])		# count
		html += td.format('center', rate)				# fail rate
		html += td.format('center nowrap', timeline)	# timeline
		html += '</tr>\n'
		num += 1

	return html+'</table>\n'

def pm_stress_test_issues():
	return getissues('http://bugzilla.kernel.org/rest.cgi', '178231')

def regex_test(issuedef, logfile):
	matches = open(logfile, 'r').read().strip().split('\n')
	print('TEST LINES:')
	for match in matches:
		print('(%d) %s' % (matches.index(match), match))
	config = configparser.ConfigParser()
	config.read(issuedef)
	sections = config.sections()
	ireq = idesc = ''
	for key in sections:
		if key.lower() == 'description':
			idesc = key
		elif key.lower() == 'requirements':
			ireq = key
	if not ireq:
		print('ERROR: issue.def has no requirements section')
		return
	if not idesc:
		print('ERROR: issue.def has no description section')
		return
	for s in [ireq, idesc]:
		for key in config.options(s):
			val = config.get(s, key)
			if key.lower().startswith('dmesgregex') or key.lower() == 'device':
				print('CHECK "%s" = "%s"' % (key, val))
				for match in matches:
					if regexmatch(val, match):
						print('(%d) %s' % (matches.index(match), match))
					else:
						print('(%d)' % matches.index(match))

if __name__ == '__main__':

	import argparse, os
	parser = argparse.ArgumentParser()
	parser.add_argument('-l', '-list', action='store_true',
		help='list bugs and show issue.def contents')
	parser.add_argument('-d', '-download', action='store_true',
		help='download issue.def files locally')
	parser.add_argument('-p', '-pickle', metavar='file',
		help='download a copy of the buglist and pickle dump it to file')
	parser.add_argument('-configtest', metavar='issuedef',
		help='verify an issue.def file is formatted correctly')
	parser.add_argument('-regextest', nargs=2, metavar=('issuedef', 'log'),
		help='search a dmesg log for matches with an issue.def file')
	args = parser.parse_args()

	if args.configtest:
		file = args.configtest
		config = configparser.ConfigParser()
		if not os.path.exists(file):
			print('ERROR: %s does not exist' % file)
			sys.exit(1)
		fp = open(file, 'rb')
		buf = fp.read().decode()
		fp.close()
		config.readfp(StringIO(buf))
		sections = config.sections()
		for s in sections:
			print(s)
			for o in config.options(s):
				print('\t%s' % o)
		sys.exit()

	if args.regextest:
		for f in args.regextest:
			if not os.path.exists(f):
				print('ERROR: %s does not exist' % f)
				sys.exit(1)
		i, l = args.regextest
		regex_test(i, l)
		sys.exit()

	if not args.p and not args.d and not args.l:
		parser.print_help()
		sys.exit(1)

	print('Collecting remote bugs and issue.def files from bugzilla(s)...')
	bugs = pm_stress_test_issues()
	print('%d BUGS FOUND' % len(bugs))

	if args.p:
		fp = open(args.p, 'w+b')
		pickle.dump(bugs, fp)
		fp.close()
		sys.exit()

	for id in sorted(bugs, key=lambda v:int(v), reverse=True):
		if args.d:
			if not bugs[id]['def']:
				continue
			desc = re.sub('[\[\]\-\+\:\(\)\{\}\/\\\&\,]+', '', bugs[id]['desc'])
			desc = re.sub('[ ]+', '-', desc.strip())
			if len(desc) > 40:
				desc = desc[:40].strip('-')
			file = 'issue-%s-%s.def' % (id, desc.lower())
			print(file)
			fp = open(file, 'wb')
			fp.write(bugs[id]['def'])
			fp.close()
			continue
		print('ISSUE ID   = %s' % id)
		print('ISSUE DESC = %s' % bugs[id]['desc'])
		print('ISSUE URL  = %s' % bugs[id]['url'])
		if bugs[id]['def']:
			print('ISSUE DEFINITION:')
			print(bugs[id]['def'].strip())
		else:
			print('ISSUE DEFINITION: MISSING')
		print('------------------------------------------------------------------------------')
