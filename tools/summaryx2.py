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
import argparse
import smtplib
sys.path += [os.path.realpath(os.path.dirname(__file__)+'/..')]
import sleepgraph as sg
import googlesheet as gs
from datetime import datetime

def dmesg_issues(file, errinfo):
	errlist = sg.Data.errlist
	lf = sg.sysvals.openlog(file, 'r')
	i = 0
	list = []
	for line in lf:
		i += 1
		m = re.match('[ \t]*(\[ *)(?P<ktime>[0-9\.]*)(\]) (?P<msg>.*)', line)
		if not m:
			continue
		t = float(m.group('ktime'))
		msg = m.group('msg')
		for err in errlist:
			if re.match(errlist[err], msg):
				if err not in errinfo:
					errinfo[err] = []
				found = False
				for entry in errinfo[err]:
					if re.match(entry['match'], msg):
						entry['count'] += 1
						found = True
						break
				if found:
					continue
				arr = msg.split()
				for j in range(len(arr)):
					if re.match('^[0-9\-\.]*$', arr[j]):
						arr[j] = '[0-9\-\.]*'
					else:
						arr[j] = arr[j]\
							.replace(']', '\]').replace('[', '\[').replace('.', '\.')\
							.replace('+', '\+').replace('*', '\*').replace('(', '\(')\
							.replace(')', '\)')
				mstr = ' '.join(arr)
				htmlfile = file.replace('.gz', '').replace('_dmesg.txt', '.html')
				if htmlfile.startswith('./'):
					htmlfile = htmlfile[2:]
				entry = {
					'line': msg,
					'match': mstr,
					'count': 1,
					'url': htmlfile
				}
				errinfo[err].append(entry)
				break

def info(file, data, errcheck, usegdrive, usehtml):
	html = open(file, 'r').read()
	line = sg.find_in_html(html, '<div class="stamp">', '</div>')
	if not line:
		print 'IGNORED: unrecognized format (%s)' % file
		return
	x = re.match('^(?P<host>.*) (?P<kernel>.*) (?P<mode>.*) \((?P<info>.*)\)', line)
	if not x:
		print 'IGNORED: summary file has more than one host/kernel/mode (%s)' % file
		return
	h, k, m, r = x.groups()
	errinfo = dict()
	resdetail = {'tests':0, 'pass': 0, 'fail': 0, 'hang': 0, 'crash': 0}
	for i in re.findall(r"[\w ]+", r):
		item = i.strip().split(' ', 1)
		if len(item) != 2:
			continue
		key, val = item[1], item[0]
		if key.startswith('fail in '):
			resdetail['fail'] += int(val)
		else:
			resdetail[key] += int(val)
	res = []
	total = resdetail['tests']
	for key in ['pass', 'fail', 'hang', 'crash']:
		val = resdetail[key]
		if val < 1:
			continue
		p = 100*float(val)/float(total)
		if usehtml:
			rout = '<tr><td nowrap>%s</td><td nowrap>%d/%d <c>(%.2f%%)</c></td></tr>' % \
				(key.upper(), val, total, p)
		else:
			rout = '%s: %d/%d (%.2f%%)' % (key.upper(), val, total, p)
		res.append(rout)
	if k not in data:
		data[k] = dict()
	if h not in data[k]:
		data[k][h] = dict()
	if m not in data[k][h]:
		data[k][h][m] = []
	vals = []
	valurls = ['', '', '', '', '', '']
	valname = ['s%smax'%m,'s%smed'%m,'s%smin'%m,'r%smax'%m,'r%smed'%m,'r%smin'%m]
	for val in valname:
		vals.append(sg.find_in_html(html, '<a href="#%s">' % val, '</a>'))
	wres = dict()
	wsus = dict()
	starttime = endtime = 0
	for test in html.split('<tr'):
		if '<th>' in test or 'class="head"' in test or '<html>' in test:
			continue
		dmesg = ''
		values = []
		out = test.split('<td')
		for i in out[1:]:
			values.append(i[1:].replace('</td>', '').replace('</tr>', '').strip())
		url = ''
		if values[13]:
			x = re.match('<a href="(?P<u>.*)">', values[13])
			if x:
				url = file.replace('summary.html', x.group('u'))
		testtime = datetime.strptime(values[4], '%Y/%m/%d %H:%M:%S')
		if url:
			x = re.match('.*/suspend-(?P<d>[0-9]*)-(?P<t>[0-9]*)/.*', url)
			if x:
				testtime = datetime.strptime(x.group('d')+x.group('t'), '%y%m%d%H%M%S')
		if not endtime or testtime > endtime:
			endtime = testtime
		if not starttime or testtime < starttime:
			starttime = testtime
		for val in valname[:3]:
			if val in values[7]:
				valurls[valname.index(val)] = url
		for val in valname[3:]:
			if val in values[8]:
				valurls[valname.index(val)] = url
		if values[9]:
			if values[9] not in wsus:
				wsus[values[9]] = 0
			wsus[values[9]] += 1
		if values[11]:
			if values[11] not in wres:
				wres[values[11]] = 0
			wres[values[11]] += 1
		if not errcheck:
			continue
		if url:
			dcheck = url.replace('.html', '_dmesg.txt.gz')
			if os.path.exists(dcheck):
				dmesg = dcheck
			elif os.path.exists(dmesg[:-3]):
				dmesg = dcheck[:-3]
		if values[6] and values[6] != 'NETLOST' and dmesg:
			dmesg_issues(dmesg, errinfo)
	last = ''
	for i in reversed(range(6)):
		if valurls[i]:
			last = valurls[i]
		else:
			valurls[i] = last
	issues = dict()
	i = 0
	for err in errinfo:
		for entry in errinfo[err]:
			issues[i] = entry
			i += 1
	cnt = 1 if resdetail['tests'] < 2 else resdetail['tests'] - 1
	avgtime = ((endtime - starttime) / cnt).total_seconds()
	data[k][h][m].append({
		'file': file,
		'results': res,
		'resdetail': resdetail,
		'sstat': [vals[0], vals[1], vals[2]],
		'rstat': [vals[3], vals[4], vals[5]],
		'sstaturl': [valurls[0], valurls[1], valurls[2]],
		'rstaturl': [valurls[3], valurls[4], valurls[5]],
		'wsd': wsus,
		'wrd': wres,
		'issues': issues,
		'testtime': avgtime,
		'totaltime': avgtime * resdetail['tests'],
	})
	x = re.match('.*/suspend-[a-z]*-(?P<d>[0-9]*)-(?P<t>[0-9]*)-[0-9]*min/summary.html', file)
	if x:
		btime = datetime.strptime(x.group('d')+x.group('t'), '%y%m%d%H%M%S')
		data[k][h][m][-1]['timestamp'] = btime
	if usegdrive:
		link = gs.gdrive_link(k, h, m, total)
		if link:
			data[k][h][m][-1]['gdrive'] = link

def text_output(data):
	text = ''
	for kernel in sorted(data):
		text += 'Sleepgraph stress test results for kernel %s (%d machines)\n' % \
			(kernel, len(data[kernel].keys()))
		for host in sorted(data[kernel]):
			text += '\n[%s]\n' % host
			for mode in sorted(data[kernel][host], reverse=True):
				for info in data[kernel][host][mode]:
					text += '%s:\n' % mode.upper()
					if 'timestamp' in info:
						text += '   Timestamp: %s\n' % info['timestamp']
					if 'gdrive' in info:
						text += '   Spreadsheet: %s\n' % info['gdrive']
					text += '   Duration: %.1f hours\n' % (info['totaltime'] / 3600)
					text += '   Avg test time: %.1f seconds\n' % info['testtime']
					text += '   Results:\n'
					for r in info['results']:
						text += '   - %s\n' % r
					text += '   Suspend: %s, %s, %s\n' % \
						(info['sstat'][0], info['sstat'][1], info['sstat'][2])
					text += '   Resume: %s, %s, %s\n' % \
						(info['rstat'][0], info['rstat'][1], info['rstat'][2])
					text += '   Worst Suspend Devices:\n'
					wsus = info['wsd']
					for i in sorted(wsus, key=lambda k:wsus[k], reverse=True):
						text += '   - %s (%d times)\n' % (i, wsus[i])
					text += '   Worst Resume Devices:\n'
					wres = info['wrd']
					for i in sorted(wres, key=lambda k:wres[k], reverse=True):
						text += '   - %s (%d times)\n' % (i, wres[i])
					issues = info['issues']
					if len(issues) < 1:
						continue
					text += '   Issues found in dmesg logs:\n'
					for e in sorted(issues, key=lambda k:issues[k]['count'], reverse=True):
						text += '   (x%d) %s\n' % (issues[e]['count'], issues[e]['line'])
	return text

def get_url(htmlfile, urlprefix):
	if not urlprefix:
		link = htmlfile
	else:
		link = os.path.join(urlprefix, htmlfile)
	return '<a href="%s">html</a>' % link

def html_output(data, urlprefix, showerrs, usegdrive):
	html = '<!DOCTYPE html>\n<html>\n<head>\n\
		<meta http-equiv="content-type" content="text/html; charset=UTF-8">\n\
		<title>SleepGraph Summary of Summaries</title>\n\
		<style type=\'text/css\'>\n\
			table {width:100%; border-collapse: collapse;}\n\
			.summary {border:1px solid;}\n\
			th {border: 1px solid black;background:#622;color:white;}\n\
			td {font: 14px "Times New Roman";}\n\
			td.issuehdr {width:90%;}\n\
			td.kerr {font: 12px "Courier";}\n\
			c {font: 12px "Times New Roman";}\n\
			ul {list-style-type: none;}\n\
			ul.devlist {list-style-type: circle; font-size: 10px; padding: 0 0 0 20px;}\n\
			tr.alt {background-color:#ddd;}\n\
			tr.hline {background-color:#000;}\n\
		</style>\n</head>\n<body>\n'

	th = '\t<th>{0}</th>\n'
	td = '\t<td nowrap>{0}</td>\n'
	tdo = '\t<td nowrap{1}>{0}</td>\n'

	for kernel in sorted(data):
		kernlink = kernel
		if usegdrive:
			link = gs.gdrive_link(kernel)
			if link:
				kernlink = '<a href="%s">%s</a>' % (link, kernel)
		html += 'Sleepgraph stress test results for kernel %s (%d machines)<br><br>\n' % \
			(kernlink, len(data[kernel].keys()))
		html += '<table class="summary">\n'
		headrow = '<tr>\n' + th.format('Host') +\
			th.format('Mode') + th.format('Duration') +\
			th.format('Results') + th.format('Suspend Time') +\
			th.format('Resume Time') + th.format('Worst Suspend Devices') +\
			th.format('Worst Resume Devices') + '</tr>\n'
		num = 0
		for host in sorted(data[kernel]):
			html += headrow
			hostlink = host
			if usegdrive:
				link = gs.gdrive_link(kernel, host)
				if link:
					hostlink = '<a href="%s">%s</a>' % (link, host)
			for mode in sorted(data[kernel][host], reverse=True):
				for info in data[kernel][host][mode]:
					trs = '<tr class=alt>\n' if num % 2 == 1 else '<tr>\n'
					html += trs
					html += tdo.format(hostlink, ' align=center')
					modelink = mode
					if usegdrive and 'gdrive' in info:
						modelink = '<a href="%s">%s</a>' % (info['gdrive'], mode)
					html += td.format(modelink)
					dur = '<table><tr>%s</tr><tr>%s</tr></table>' % \
						(td.format('%.1f hours' % (info['totaltime'] / 3600)),
						td.format('%d x %.1f sec' % (info['resdetail']['tests'], info['testtime'])))
					html += td.format(dur)
					html += td.format('<table>' + ''.join(info['results']) + '</table>')
					for entry in ['sstat', 'rstat']:
						tdhtml = '<table>'
						for val in info[entry]:
							tdhtml += '<tr><td nowrap>%s</td></tr>' % val
						html += td.format(tdhtml+'</table>')
					for entry in ['wsd', 'wrd']:
						tdhtml = '<ul class=devlist>'
						list = info[entry]
						for i in sorted(list, key=lambda k:list[k], reverse=True):
							tdhtml += '<li>%s (x%d)</li>' % (i, list[i])
						html += td.format(tdhtml+'</ul>')
					html += '</tr>\n'
					if not showerrs:
						continue
					html += '%s<td colspan=8><table border=1 width="100%%">' % trs
					html += '%s<td colspan=6 class="issuehdr"><b>Issues found</b></td><td><b>Count</b></td><td><b>html</b></td>\n</tr>' % trs
					issues = info['issues']
					if len(issues) > 0:
						for e in sorted(issues, key=lambda k:issues[k]['count'], reverse=True):
							html += '%s<td colspan=6 class="kerr">%s</td><td>%d times</td><td>%s</td></tr>\n' % \
								(trs, issues[e]['line'], issues[e]['count'], get_url(issues[e]['url'], urlprefix))
					else:
						html += '%s<td colspan=8>NONE</td></tr>\n' % trs
					html += '</table></td></tr>\n'
			num += 1
		html += '</table><br>\n'
	html += '</body>\n</html>\n'
	return html

def send_mail(server, sender, receiver, type, subject, contents):
	message = \
		'From: %s\n'\
		'To: %s\n'\
		'MIME-Version: 1.0\n'\
		'Content-type: %s\n'\
		'Subject: %s\n\n' % (sender, receiver, type, subject)
	receivers = receiver.split(';')
	message += contents
	smtpObj = smtplib.SMTP(server, 25)
	smtpObj.sendmail(sender, receivers, message)

def doError(msg, help=False):
	print("ERROR: %s") % msg
	if(help == True):
		printHelp()
	sys.exit()

if __name__ == '__main__':
	parser = argparse.ArgumentParser(description='Generate a summary of a summaries')
	parser.add_argument('--html', action='store_true',
		help='output in html (default is text)')
	parser.add_argument('--sheet', action='store_true',
		help='output in google sheet (default is text)')
	parser.add_argument('--issues', action='store_true',
		help='extract issues from dmesg files (WARNING/ERROR etc)')
	parser.add_argument('--gdrive', action='store_true',
		help='include google drive links to the spreadsheets for each summary')
	parser.add_argument('--mail', nargs=3, metavar=('server', 'sender', 'receiver'),
		help='send the output via email')
	parser.add_argument('--subject', metavar='string',
		help='the subject line for the email')
	parser.add_argument('--urlprefix', metavar='url',
		help='url prefix to use in links to timelines')
	parser.add_argument('--output', metavar='filename',
		help='output the results to file')
	parser.add_argument('folder', help='folder to search for summaries')
	args = parser.parse_args()

	if not os.path.exists(args.folder) or not os.path.isdir(args.folder):
		doError('Folder not found')

	if args.sheet:
		args.gdrive = True

	if args.gdrive:
		gs.initGoogleAPIs()

	if args.urlprefix:
		if args.urlprefix[-1] == '/':
			args.urlprefix = args.urlprefix[:-1]

	data = dict()
	for dirname, dirnames, filenames in os.walk(args.folder):
		for filename in filenames:
			if filename == 'summary.html':
				file = os.path.join(dirname, filename)
				info(file, data, args.issues, args.gdrive, args.html)

	if args.sheet:
		for kernel in sorted(data):
			print('creating summary for %s' % kernel)
			gs.createSummarySpreadsheet(kernel, data[kernel], args.urlprefix)
		sys.exit(0)
	elif args.html:
		out = html_output(data, args.urlprefix, args.issues, args.gdrive)
	else:
		out = text_output(data)

	if args.output:
		fp = open(args.output, 'w')
		fp.write(out)
		fp.close()

	if args.mail:
		server, sender, receiver = args.mail
		subject = args.subject if args.subject else 'Summary of sleepgraph batch tests'
		type = 'text/html' if args.html else 'text'
		send_mail(server, sender, receiver, type, subject, out)
	elif not args.output:
		print out
