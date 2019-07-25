#!/usr/bin/python

import sys
import base64
import re
import json
import requests
import configparser
from io import StringIO
try:
	from urllib import urlencode
except ImportError:
	from urllib.parse import urlencode

def webrequest(url):
	try:
		res = requests.get(url)
	except Exception as e:
		res = 0
		print('URL: %s\nException: %s' % (url, str(e)))
	if res == 0:
		print('ERROR: res == 0')
		return dict()
	res.raise_for_status()
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
			desc = '%s [%s %s]' % (bug['summary'], bug['status'], bug['resolution'])
		else:
			desc = '%s [%s]' % (bug['summary'], bug['status'])
		out[id] = {
			'def': idef,
			'matches': 0,
			'url': showurl.format(id),
			'desc': desc,
		}
	return out

def loadissue(file):
	out = dict()
	out['1'] = {
		'def': open(file, 'rb').read(),
		'matches': 0,
		'url': '',
		'desc': 'custom issue',
	}
	return out

def countFormat(count, total):
	p = 100*float(count)/float(total)
	return '%d / %d (%.2f%%)' % (count, total, p)

def regexmatch(mstr, line):
	if mstr in line or re.match(mstr, line):
		return True
	return False

def check_issue(host, val, issues, testruns, bugdata):
	for issue in issues:
		if regexmatch(val, issue['line']):
			urls = issue['urls']
			url = urls[host][0] if host in urls else ''
			bugdata['found'] = url
			bugdata['count'] = issue['tests']
			break

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

def check_call_time(mstr, testruns, bugdata):
	callstr, target, greater = getComparison(mstr)
	if not callstr or target < 0:
		return
	match = {'count':0,'worst':0,'url':''}
	name, args, tm = functionInfo(callstr)
	for data in testruns:
		found = False
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
			if greater and t > target:
				if t > match['worst']:
					match['worst'] = t
					match['url'] = data['url']
				found = True
			elif not greater and t < target:
				if t < match['worst']:
					match['worst'] = t
					match['url'] = data['url']
				found = True
		if found:
			match['count'] += 1
	bugdata['found'] = match['url']
	bugdata['count'] = match['count']

def check_device_time(phase, mstr, testruns, bugdata):
	devstr, target, greater = getComparison(mstr)
	if not devstr or target < 0:
		return
	match = dict()
	for data in testruns:
		if phase not in data['devlist']:
			break
		for dev in data['devlist'][phase]:
			name = dev.split(' {')[0] if '{' in dev else dev
			if '[' in name:
				name = name.split(' [')[-1].replace(']', '')
			if not regexmatch(devstr, name):
				continue
			if name not in match:
				match[name] = {'count':0,'worst':0,'url':''}
			val = data['devlist'][phase][dev]
			if greater and val > target:
				if val > match[name]['worst']:
					match[name]['worst'] = val
					match[name]['url'] = data['url']
				match[name]['count'] += 1
			elif not greater and val < target:
				if val < match[name]['worst']:
					match[name]['worst'] = val
					match[name]['url'] = data['url']
				match[name]['count'] += 1
	for i in sorted(match, key=lambda k:match[k]['count'], reverse=True):
		bugdata['found'] = match[i]['url']
		bugdata['count'] = match[i]['count']
		break

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

def find_device(mstr, testruns):
	for data in testruns[:5]:
		if 'suspend' not in data['devlist']:
			break
		for dev in data['devlist']['suspend']:
			name = dev.split(' {')[0] if '{' in dev else dev
			name = name.split(' [')[-1].replace(']', '') if '[' in name else name
			if regexmatch(mstr, name):
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
		config.readfp(StringIO(buglist[id]['def'].decode()))
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
		for key in config.options(idesc):
			if bugdata['found']:
				break
			val = config.get(idesc, key)
			if key.lower().startswith('dmesgregex'):
				check_issue(desc['host'], val, issues, testruns, bugdata)
			elif key.lower() in ['devicesuspend', 'deviceresume']:
				check_device_time(key[6:].lower(), val, testruns, bugdata)
			elif key.lower() == 'calltime':
				check_call_time(val, testruns, bugdata)
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
	out = getissues('http://bugzilla.kernel.org/rest.cgi', '178231')
	outb = getissues('http://bugs.freedesktop.org/rest.cgi', '110785')
	for id in outb:
		if id in out:
			out[id+'_fd'] = outb[id]
		else:
			out[id] = outb[id]
	return out

def regex_test(issuedef, logfile):
	matches = open(logfile, 'r').read().strip().split('\n')
	print('TEST LINES:')
	for match in matches:
		print('(%d) %s' % (matches.index(match), match))
	config = configparser.ConfigParser()
	config.read(issuedef)
	sections = config.sections()
	idesc = ''
	for key in sections:
		if key.lower() == 'description':
			idesc = key
	if not idesc:
		print('ERROR: issue.def has no description section')
		return
	for key in config.options(idesc):
		val = config.get(idesc, key)
		if key.lower().startswith('dmesgregex'):
			print('CHECK "%s" = "%s"' % (key, val))
			for match in matches:
				if regexmatch(val, match):
					print('(%d) %s' % (matches.index(match), match))
				else:
					print('(%d)' % matches.index(match))

if __name__ == '__main__':

	import argparse, os
	parser = argparse.ArgumentParser()
	parser.add_argument('-configtest', metavar='issuedef')
	parser.add_argument('-regextest', nargs=2, metavar=('issuedef', 'matchfile'))
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

	print('Collecting remote bugs and issue.def files from bugzilla(s)...')
	bugs = pm_stress_test_issues()
	print('%d BUGS FOUND' % len(bugs))
	for id in sorted(bugs, key=lambda v:int(v), reverse=True):
		print('ISSUE ID   = %s' % id)
		print('ISSUE DESC = %s' % bugs[id]['desc'])
		print('ISSUE URL  = %s' % bugs[id]['url'])
		if bugs[id]['def']:
			print('ISSUE DEFINITION:')
			print(bugs[id]['def'].strip())
		else:
			print('ISSUE DEFINITION: MISSING')
		print('------------------------------------------------------------------------------')
