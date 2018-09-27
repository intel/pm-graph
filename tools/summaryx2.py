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

def gdrive_link(kernel, host='', mode='', total=0):
	linkfmt = 'https://drive.google.com/open?id={0}'
	if kernel and host and mode:
		gpath = 'pm-graph-test/%s/%s/%s-x%d-summary' % (kernel, host, mode, total)
	elif kernel and host:
		gpath = 'pm-graph-test/%s/%s' % (kernel, host)
	else:
		gpath = 'pm-graph-test/%s' % (kernel)
	id = gs.gdrive_find(gpath)
	if id:
		return linkfmt.format(id)
	return ''

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
						arr[j] = arr[j].replace(']', '\]').replace('[', '\[').replace('.', '\.').replace('+', '\+')
				mstr = ' '.join(arr)
				entry = {
					'line': msg,
					'match': mstr,
					'count': 1,
					'url': file
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
	res = []
	total = -1
	for i in re.findall(r"[\w ]+", r):
		item = i.strip().split(' ', 1)
		if len(item) != 2:
			continue
		key, val = item[1], item[0]
		if key.startswith('fail in '):
			if usehtml:
				key = 'FAIL<c>(%s)</c>' % key[8:]
			else:
				key = 'FAIL(%s)' % key[8:]
		else:
			key = key.upper()
		if key == 'TESTS':
			total = float(val)
		elif total > 0:
			p = 100*float(val)/total
			if usehtml:
				rout = '<tr><td>%s</td><td>%s/%.0f <c>(%.1f%%)</c></td></tr>' % \
					(key, val, total, p)
			else:
				rout = '%s: %s/%.0f (%.1f%%)' % (key, val, total, p)
			res.append(rout)
	if k not in data:
		data[k] = dict()
	if h not in data[k]:
		data[k][h] = dict()
	if m not in data[k][h]:
		data[k][h][m] = []
	smax = sg.find_in_html(html, '<a href="#s%smax">' % m, '</a>')
	smed = sg.find_in_html(html, '<a href="#s%smed">' % m, '</a>')
	smin = sg.find_in_html(html, '<a href="#s%smin">' % m, '</a>')
	rmax = sg.find_in_html(html, '<a href="#r%smax">' % m, '</a>')
	rmed = sg.find_in_html(html, '<a href="#r%smed">' % m, '</a>')
	rmin = sg.find_in_html(html, '<a href="#r%smin">' % m, '</a>')
	wres = dict()
	wsus = dict()
	for test in html.split('<tr'):
		if '<th>' in test or 'class="head"' in test or '<html>' in test:
			continue
		dmesg = ''
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
		if not errcheck:
			continue
		if values[13]:
			x = re.match('<a href="(?P<u>.*)">', values[13])
			dcheck = file.replace('summary.html', x.group('u').replace('.html', '_dmesg.txt.gz'))
			if os.path.exists(dcheck):
				dmesg = dcheck
			elif os.path.exists(dmesg[:-3]):
				dmesg = dcheck[:-3]
		if values[6] and values[6] != 'NETLOST' and dmesg:
			dmesg_issues(dmesg, errinfo)
	wstext = dict()
	for i in sorted(wsus, key=lambda k:wsus[k], reverse=True):
		wstext[wsus[i]] = i
	wrtext = dict()
	for i in sorted(wres, key=lambda k:wres[k], reverse=True):
		wrtext[wres[i]] = i
	issues = dict()
	for err in errinfo:
		for entry in errinfo[err]:
			issues[entry['count']] = entry
	data[k][h][m].append({
		'file': file,
		'results': res,
		'sstat': [smax, smed, smin],
		'rstat': [rmax, rmed, rmin],
		'wsd': wstext,
		'wrd': wrtext,
		'issues': issues,
	})
	if usegdrive:
		link = gdrive_link(k, h, m, total)
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
					if 'gdrive' in info:
						text += '   Spreadsheet: %s\n' % info['gdrive']
					for r in info['results']:
						text += '   %s\n' % r
					text += '   Suspend: %s, %s, %s\n' % \
						(info['sstat'][0], info['sstat'][1], info['sstat'][2])
					text += '   Resume: %s, %s, %s\n' % \
						(info['rstat'][0], info['rstat'][1], info['rstat'][2])
					text += '   Worst Suspend Devices:\n'
					for cnt in sorted(info['wsd'], reverse=True):
						text += '   - %s (%d times)\n' % (info['wsd'][cnt], cnt)
					text += '   Worst Resume Devices:\n'
					for cnt in sorted(info['wrd'], reverse=True):
						text += '   - %s (%d times)\n' % (info['wrd'][cnt], cnt)
					issues = info['issues']
					if len(issues) < 1:
						continue
					text += '   Issues found in dmesg logs:\n'
					for e in sorted(issues, reverse=True):
						text += '   (x%d) %s\n' % (e, issues[e]['line'])
	return text

def get_url(dmesgfile, urlprefix):
	htmlfile = dmesgfile.replace('.gz', '').replace('_dmesg.txt', '.html')
	if htmlfile.startswith('./'):
		htmlfile = htmlfile[2:]
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
			link = gdrive_link(kernel)
			if link:
				kernlink = '<a href="%s">%s</a>' % (link, kernel)
		html += 'Sleepgraph stress test results for kernel %s (%d machines)<br><br>\n' % \
			(kernlink, len(data[kernel].keys()))
		html += '<table class="summary">\n'
		headrow = '<tr>\n' + th.format('Host') +\
			th.format('Mode') + th.format('Results') + th.format('Suspend Time') +\
			th.format('Resume Time') + th.format('Worst Suspend Devices') +\
			th.format('Worst Resume Devices') + '</tr>\n'
		num = 0
		for host in sorted(data[kernel]):
			html += headrow
			hostlink = host
			if usegdrive:
				link = gdrive_link(kernel, host)
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
					html += td.format('<table>' + ''.join(info['results']) + '</table>')
					for entry in ['sstat', 'rstat']:
						tdhtml = '<table>'
						for val in info[entry]:
							tdhtml += '<tr><td nowrap>%s</td></tr>' % val
						html += td.format(tdhtml+'</table>')
					for entry in ['wsd', 'wrd']:
						tdhtml = '<ul class=devlist>'
						for cnt in sorted(info[entry], reverse=True):
							tdhtml += '<li>%s (x%d)</li>' % (info[entry][cnt], cnt)
						html += td.format(tdhtml+'</ul>')
					html += '</tr>\n'
					if not showerrs:
						continue
					html += '%s<td colspan=7><table border=1 width="100%%">' % trs
					html += '%s<td colspan=5 class="issuehdr"><b>Issues found</b></td><td><b>Count</b></td><td><b>html</b></td>\n</tr>' % trs
					issues = info['issues']
					if len(issues) > 0:
						for e in sorted(issues, reverse=True):
							html += '%s<td colspan=5 class="kerr">%s</td><td>%d times</td><td>%s</td></tr>\n' % \
								(trs, issues[e]['line'], e, get_url(issues[e]['url'], urlprefix))
					else:
						html += '%s<td colspan=7>NONE</td></tr>\n' % trs
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

	if args.html:
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
