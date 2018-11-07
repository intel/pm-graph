#!/usr/bin/python
#
# Google Sheet Creator
#
# If libraries are missing, use this command to install them:
#  pip install --upgrade google-api-python-client oauth2client
#
# To run -setup without local browser use this command:
#  ./googlesheet.py -setup --noauth_local_webserver
#
import os
import sys
import warnings
import re
import time
from datetime import date, datetime, timedelta
import sleepgraph as sg
try:
	import httplib2
except:
	print 'Missing libraries, please run this command:'
	print 'sudo apt-get install python-httplib2'
	sys.exit(1)
try:
	import apiclient.discovery as discovery
	import oauth2client
except:
	print 'Missing libraries, please run this command:'
	print 'sudo apt-get install python-pip'
	print 'sudo pip install --upgrade google-api-python-client oauth2client'
	sys.exit(1)

gdrive = 0
gsheet = 0

def setupGoogleAPIs():
	global gsheet, gdrive

	print '\nSetup involves creating a "credentials.json" file with your account credentials.'
	print 'This requires that you enable access to the google sheets and drive apis for your account.\n'
	SCOPES = 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
	# look for a credentials.json file somewhere in our paths
	cf = sg.sysvals.configFile('credentials.json')
	if not cf:
		cf = 'credentials.json'
	store = oauth2client.file.Storage(cf)
	creds = store.get()
	if not creds or creds.invalid:
		if not os.path.exists('client_secret.json'):
			print 'ERROR: you are missing the client_secret.json file\n'
			print 'Please add client_secret.json by following these instructions:'
			print 'https://developers.google.com/drive/api/v3/quickstart/python.'
			print 'Click "ENABLE THE DRIVE API" and select the pm-graph project (create a new one if pm-graph is absent)'
			print 'Then rename the downloaded credentials.json file to client_secret.json and re-run -setup\n'
			print 'If the pm-graph project is not available, you must also add sheet permissions to your project.'
			print 'https://developers.google.com/sheets/api/quickstart/python.'
			print 'Click "ENABLE THE GOOGLE SHEETS API" and select your project.'
			print 'Then rename the downloaded credentials.json file to client_secret.json and re-run -setup\n'
			sys.exit()
		flow = oauth2client.client.flow_from_clientsecrets('client_secret.json', SCOPES)
		# this is required because this call includes all the command line arguments
		print 'Please login and allow access to these apis.'
		print 'The credentials file will be downloaded automatically on completion.'
		del sys.argv[sys.argv.index('-setup')]
		creds = oauth2client.tools.run_flow(flow, store)
	else:
		print 'Your credentials.json file appears valid, please delete it to re-run setup'

def initGoogleAPIs():
	global gsheet, gdrive

	SCOPES = 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
	cf = sg.sysvals.configFile('credentials.json')
	if not cf:
		print 'ERROR: no credentials.json file found (please run -setup)'
		sys.exit(1)
	store = oauth2client.file.Storage(cf)
	creds = store.get()
	if not creds or creds.invalid:
		print 'ERROR: failed to get google api credentials (please run -setup)'
		sys.exit(1)
	gdrive = discovery.build('drive', 'v3', http=creds.authorize(httplib2.Http()))
	gsheet = discovery.build('sheets', 'v4', http=creds.authorize(httplib2.Http()))

def gdrive_find(gpath):
	dir, file = os.path.dirname(gpath), os.path.basename(gpath)
	pid = gdrive_mkdir(dir, readonly=True)
	if not pid:
		return ''
	query = 'trashed = false and \'%s\' in parents and name = \'%s\'' % (pid, file)
	results = gdrive.files().list(q=query).execute()
	out = results.get('files', [])
	if len(out) > 0 and 'id' in out[0]:
		return out[0]['id']
	return ''

def gdrive_link(kernel, host='', mode='', total=0):
	linkfmt = 'https://drive.google.com/open?id={0}'
	if kernel and host and mode:
		gpath = 'pm-graph-test/%s/%s/%s-x%d-summary' % (kernel, host, mode, total)
	elif kernel and host:
		gpath = 'pm-graph-test/%s/%s' % (kernel, host)
	else:
		gpath = 'pm-graph-test/%s' % (kernel)
	id = gdrive_find(gpath)
	if id:
		return linkfmt.format(id)
	return ''

def gdrive_mkdir(dir='', readonly=False):
	global gsheet, gdrive

	fmime = 'application/vnd.google-apps.folder'
	pid = 'root'
	if not dir:
		return pid
	for subdir in dir.split('/'):
		# get a list of folders in this subdir
		query = 'trashed = false and mimeType = \'%s\' and \'%s\' in parents' % (fmime, pid)
		results = gdrive.files().list(q=query).execute()
		id = ''
		for item in results.get('files', []):
			if item['name'] == subdir:
				id = item['id']
				break
		# id this subdir exists, move on
		if id:
			pid = id
			continue
		# create the subdir
		if readonly:
			return ''
		else:
			metadata = {'name': subdir, 'mimeType': fmime, 'parents': [pid]}
			file = gdrive.files().create(body=metadata, fields='id').execute()
			pid = file.get('id')
	return pid

def formatSpreadsheet(id):
	global gsheet, gdrive

	highlight_range = {
		'sheetId': 1,
		'startRowIndex': 1,
		'startColumnIndex': 5,
		'endColumnIndex': 6,
	}
	sigdig_range = {
		'sheetId': 1,
		'startRowIndex': 1,
		'startColumnIndex': 7,
		'endColumnIndex': 13,
	}
	requests = [{
		'addConditionalFormatRule': {
			'rule': {
				'ranges': [ highlight_range ],
				'booleanRule': {
					'condition': {
						'type': 'TEXT_NOT_CONTAINS',
						'values': [ { 'userEnteredValue': 'pass' } ]
					},
					'format': {
						'textFormat': { 'foregroundColor': { 'red': 1.0 } }
					}
				}
			},
			'index': 0
		}
	},
	{'autoResizeDimensions': {'dimensions': {'sheetId': 0,
		'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 1}}},
	{'autoResizeDimensions': {'dimensions': {'sheetId': 0,
		'dimension': 'COLUMNS', 'startIndex': 2, 'endIndex': 3}}},
	{'autoResizeDimensions': {'dimensions': {'sheetId': 1,
		'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 13}}},
	{'autoResizeDimensions': {'dimensions': {'sheetId': 2,
		'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 5}}},
	{'autoResizeDimensions': {'dimensions': {'sheetId': 3,
		'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 5}}},
	{'updateBorders': {
		'range': {'sheetId': 0, 'startRowIndex': 0, 'endRowIndex': 4,
			'startColumnIndex': 0, 'endColumnIndex': 3},
		'top': {'style': 'SOLID', 'width': 3},
		'left': {'style': 'SOLID', 'width': 3},
		'bottom': {'style': 'SOLID', 'width': 2},
		'right': {'style': 'SOLID', 'width': 2}},
	},
	{'updateBorders': {
		'range': {'sheetId': 0, 'startRowIndex': 4, 'endRowIndex': 5,
			'startColumnIndex': 0, 'endColumnIndex': 3},
		'bottom': {'style': 'DASHED', 'width': 1}},
	},
	{
		'repeatCell': {
			'range': sigdig_range,
			'cell': {
				'userEnteredFormat': {
					'numberFormat': {
						'type': 'NUMBER',
						'pattern': '0.000'
					}
				}
			},
			'fields': 'userEnteredFormat.numberFormat'
		},
	}]
	body = {
		'requests': requests
	}
	response = gsheet.spreadsheets().batchUpdate(spreadsheetId=id, body=body).execute()
	print('{0} cells updated.'.format(len(response.get('replies'))));

def deleteDuplicate(folder, name):
	global gsheet, gdrive

	# remove any duplicate spreadsheets
	query = 'trashed = false and \'%s\' in parents and name = \'%s\'' % (folder, name)
	results = gdrive.files().list(q=query).execute()
	items = results.get('files', [])
	for item in items:
		print 'deleting duplicate - %s (%s)' % (item['name'], item['id'])
		try:
			gdrive.files().delete(fileId=item['id']).execute()
		except errors.HttpError, error:
			doError('gdrive api error on delete file')

def createSpreadsheet(testruns, devall, folder, urlhost, title):
	global gsheet, gdrive

	deleteDuplicate(folder, title)

	# create the headers row
	gslink = '=HYPERLINK("{0}","{1}")'
	headers = [
		['#','Mode','Host','Kernel','Time','Result','Issues','Suspend',
		'Resume','Worst Suspend Device','SD Time','Worst Resume Device','RD Time',
		'Comments','Timeline'],
		['Device Name', 'Count', 'Average Time', 'Worst Time', 'Detail']
	]

	headrows = []
	for header in headers:
		headrow = []
		for name in header:
			headrow.append({
				'userEnteredValue':{'stringValue':name},
				'userEnteredFormat':{
					'textFormat': {'bold': True},
					'horizontalAlignment':'CENTER',
					'borders':{'bottom':{'style':'SOLID'}},
				},
			})
		headrows.append(headrow)

	# assemble the device data into spreadsheets
	limit = 1
	devdata = {
		'suspend': [{'values':headrows[1]}],
		'resume': [{'values':headrows[1]}],
	}
	for type in sorted(devall, reverse=True):
		devlist = devall[type]
		for name in sorted(devlist, key=lambda k:devlist[k]['worst'], reverse=True):
			data = devall[type][name]
			if data['average'] < limit:
				continue
			url = os.path.join(urlhost, data['url'])
			r = {'values':[
				{'userEnteredValue':{'stringValue':data['name']}},
				{'userEnteredValue':{'numberValue':data['count']}},
				{'userEnteredValue':{'numberValue':data['average']}},
				{'userEnteredValue':{'numberValue':data['worst']}},
				{'userEnteredValue':{'formulaValue':gslink.format(url, 'html')}},
			]}
			devdata[type].append(r)

	# assemble the entire spreadsheet into testdata
	i = 1
	results = []
	desc = {'summary': os.path.join(urlhost, 'summary.html')}
	testdata = [{'values':headrows[0]}]
	for test in sorted(testruns, key=lambda v:(v['mode'], v['host'], v['kernel'], v['time'])):
		for key in ['host', 'mode', 'kernel']:
			if key not in desc:
				desc[key] = test[key]
		if test['result'] not in desc:
			if test['result'].startswith('fail ') and 'fail' not in results:
				results.append('fail')
			results.append(test['result'])
			desc[test['result']] = 0
		desc[test['result']] += 1
		url = os.path.join(urlhost, test['url'])
		r = {'values':[
			{'userEnteredValue':{'numberValue':i}},
			{'userEnteredValue':{'stringValue':test['mode']}},
			{'userEnteredValue':{'stringValue':test['host']}},
			{'userEnteredValue':{'stringValue':test['kernel']}},
			{'userEnteredValue':{'stringValue':test['time']}},
			{'userEnteredValue':{'stringValue':test['result']}},
			{'userEnteredValue':{'stringValue':test['issues']}},
			{'userEnteredValue':{'numberValue':float(test['suspend'])}},
			{'userEnteredValue':{'numberValue':float(test['resume'])}},
			{'userEnteredValue':{'stringValue':test['sus_worst']}},
			{'userEnteredValue':{'numberValue':float(test['sus_worsttime'])}},
			{'userEnteredValue':{'stringValue':test['res_worst']}},
			{'userEnteredValue':{'numberValue':float(test['res_worsttime'])}},
			{'userEnteredValue':{'stringValue':''}},
			{'userEnteredValue':{'stringValue':url}},
		]}
		testdata.append(r)
		i += 1
	total = i - 1
	desc['total'] = '%d' % total
	fail = 0
	for key in results:
		if key not in desc:
			continue
		val = desc[key]
		perc = 100.0*float(val)/float(total)
		desc[key] = '%d (%.1f%%)' % (val, perc)
		if key.startswith('fail '):
			fail += val
	if fail:
		perc = 100.0*float(fail)/float(total)
		desc['fail'] = '%d (%.1f%%)' % (fail, perc)

	# create the summary page info
	summdata = []
	comments = {
		'total':'total number of tests run',
		'pass':'%s entered successfully' % testruns[0]['mode'],
		'fail':'%s NOT entered' % testruns[0]['mode'],
		'hang':'system unrecoverable (network lost, no data generated on target)',
		'crash':'sleepgraph failed to finish (from instability after resume or tool failure)',
	}
	# sort the results keys
	pres = ['pass'] if 'pass' in results else []
	fres = []
	for key in results:
		if key.startswith('fail'):
			fres.append(key)
	pres += sorted(fres)
	pres += ['hang'] if 'hang' in results else []
	pres += ['crash'] if 'crash' in results else []
	# add to the spreadsheet
	for key in ['host', 'mode', 'kernel', 'summary', 'total'] + pres:
		comment = comments[key] if key in comments else ''
		if key.startswith('fail '):
			comment = '%s NOT entered (aborted in %s)' % (testruns[0]['mode'], key.split()[-1])
		val = desc[key]
		r = {'values':[
			{'userEnteredValue':{'stringValue':key},
				'userEnteredFormat':{'textFormat': {'bold': True}}},
			{'userEnteredValue':{'stringValue':val}},
			{'userEnteredValue':{'stringValue':comment},
				'userEnteredFormat':{'textFormat': {'italic': True}}},
		]}
		summdata.append(r)

	# create the spreadsheet
	data = {
		'properties': {
			'title': title
		},
		'sheets': [
			{
				'properties': {'sheetId': 0, 'title': 'Summary'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': summdata}
				]
			},
			{
				'properties': {'sheetId': 1, 'title': 'Test Data'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': testdata}
				]
			},
			{
				'properties': {'sheetId': 2, 'title': 'Suspend Devices'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': devdata['suspend']}
				]
			},
			{
				'properties': {'sheetId': 3, 'title': 'Resume Devices'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': devdata['resume']}
				]
			},
		],
		'namedRanges': [
			{'name':'Test', 'range':{'sheetId':1,'startColumnIndex':0,'endColumnIndex':1}},
		],
	}
	sheet = gsheet.spreadsheets().create(body=data).execute()
	if 'spreadsheetId' not in sheet:
		return ''
	id = sheet['spreadsheetId']

	# special formatting
	formatSpreadsheet(id)

	# move the spreadsheet into its proper folder
	file = gdrive.files().get(fileId=id, fields='parents').execute()
	prevpar = ','.join(file.get('parents'))
	file = gdrive.files().update(fileId=id, addParents=folder,
		removeParents=prevpar, fields='id, parents').execute()
	print 'spreadsheet id: %s' % id
	if 'spreadsheetUrl' not in sheet:
		return id
	return sheet['spreadsheetUrl']

def createSummarySpreadsheet(kernel, data, urlprefix):
	global gsheet, gdrive

	title = 'summary_%s' % kernel
	gpath = 'pm-graph-test/%s' % kernel
	kfid = gdrive_find(gpath)
	if not kfid:
		print('MISSING on google drive: %s' % gpath)
		return False

	deleteDuplicate(kfid, title)

	# create the headers row
	hosts = []
	for host in sorted(data):
		hosts.append(host)
	headers = [
		['Host','Mode','Duration','Avg(t)','Total','Pass','Fail',
			'Hang','Crash','Smax','Smed','Smin','Rmax','Rmed','Rmin'],
		['Host','Mode','Issue','Count','First instance'],
		['Device','Count']+hosts,
	]
	headrows = []
	for header in headers:
		headrow = []
		for name in header:
			headrow.append({
				'userEnteredValue':{'stringValue':name},
				'userEnteredFormat':{
					'textFormat': {'bold': True},
					'horizontalAlignment':'CENTER',
					'borders':{'bottom':{'style':'SOLID'}},
				},
			})
		headrows.append(headrow)

	gslink = '=HYPERLINK("{0}","{1}")'
	gslinkval = '=HYPERLINK("{0}",{1})'
	gsperc = '=({0}/{1})'
	s0data = [{'values':headrows[0]}]
	hostlink = dict()
	worst = {'wsd':dict(), 'wrd':dict()}
	for host in sorted(data):
		hostlink[host] = gdrive_link(kernel, host)
		if not hostlink[host]:
			print('MISSING on google drive: pm-graph-test/%s/%s' % (kernel, host))
			continue
		for mode in sorted(data[host], reverse=True):
			for info in data[host][mode]:
				for entry in worst:
					for dev in info[entry]:
						if dev not in worst[entry]:
							worst[entry][dev] = {'count': 0}
							for h in hosts:
								worst[entry][dev][h] = 0
						worst[entry][dev]['count'] += info[entry][dev]
						worst[entry][dev][host] += info[entry][dev]
				statvals = []
				for entry in ['sstat', 'rstat']:
					for i in range(3):
						if '=' in info[entry][i]:
							val = float(info[entry][i].split('=')[-1])
							if urlprefix:
								url = os.path.join(urlprefix, info[entry+'url'][i])
								statvals.append({'formulaValue':gslinkval.format(url, val)})
							else:
								statvals.append({'numberValue':val})
						else:
							statvals.append({'stringValue':''})
				if 'gdrive' in info:
					modelink = {'formulaValue':gslink.format(info['gdrive'], mode)}
				else:
					modelink = {'stringValue': mode}
				rd = info['resdetail']
				r = {'values':[
					{'userEnteredValue':{'formulaValue':gslink.format(hostlink[host], host)}},
					{'userEnteredValue':modelink},
					{'userEnteredValue':{'stringValue':'%.1f hours' % (info['totaltime']/3600)}},
					{'userEnteredValue':{'stringValue':'%.1f sec' % info['testtime']}},
					{'userEnteredValue':{'numberValue':rd['tests']}},
					{'userEnteredValue':{'formulaValue':gsperc.format(rd['pass'], rd['tests'])}},
					{'userEnteredValue':{'formulaValue':gsperc.format(rd['fail'], rd['tests'])}},
					{'userEnteredValue':{'formulaValue':gsperc.format(rd['hang'], rd['tests'])}},
					{'userEnteredValue':{'formulaValue':gsperc.format(rd['crash'], rd['tests'])}},
					{'userEnteredValue':statvals[0]},
					{'userEnteredValue':statvals[1]},
					{'userEnteredValue':statvals[2]},
					{'userEnteredValue':statvals[3]},
					{'userEnteredValue':statvals[4]},
					{'userEnteredValue':statvals[5]},
				]}
				s0data.append(r)

	s1data = []
	for host in sorted(data):
		for mode in sorted(data[host], reverse=True):
			for info in data[host][mode]:
				if 'issues' not in info:
					continue
				if 'gdrive' in info:
					modelink = {'formulaValue':gslink.format(info['gdrive'], mode)}
				else:
					modelink = {'stringValue': mode}
				issues = info['issues']
				for e in sorted(issues, key=lambda k:issues[k]['count'], reverse=True):
					if urlprefix:
						url = os.path.join(urlprefix, issues[e]['url'])
						html = {'formulaValue':gslink.format(url, 'html')}
					else:
						html = {'stringValue':issues[e]['url']}
					r = {'values':[
						{'userEnteredValue':{'formulaValue':gslink.format(hostlink[host], host)}},
						{'userEnteredValue':modelink},
						{'userEnteredValue':{'stringValue':issues[e]['line']}},
						{'userEnteredValue':{'numberValue':issues[e]['count']}},
						{'userEnteredValue':html},
					]}
					s1data.append(r)
	# sort the data by count
	s1data = [{'values':headrows[1]}] + \
		sorted(s1data, key=lambda k:k['values'][3]['userEnteredValue']['numberValue'], reverse=True)

	s2data = {'wsd':0, 'wrd':0}
	for entry in worst:
		s2data[entry] = [{'values':headrows[2]}]
		for dev in sorted(worst[entry], key=lambda k:worst[entry][k]['count'], reverse=True):
			r = {'values':[
				{'userEnteredValue':{'stringValue':dev}},
				{'userEnteredValue':{'numberValue':worst[entry][dev]['count']}},
			]}
			for h in hosts:
				r['values'].append({'userEnteredValue':{'numberValue':worst[entry][dev][h]}})
			s2data[entry].append(r)

	# create the spreadsheet
	data = {
		'properties': {
			'title': title
		},
		'sheets': [
			{
				'properties': {'sheetId': 0, 'title': 'Results'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': s0data}
				]
			},
			{
				'properties': {'sheetId': 1, 'title': 'Issues'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': s1data}
				]
			},
			{
				'properties': {'sheetId': 2, 'title': 'Worst Suspend Devices'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': s2data['wsd']}
				]
			},
			{
				'properties': {'sheetId': 3, 'title': 'Worst Resume Devices'},
				'data': [
					{'startRow': 0, 'startColumn': 0, 'rowData': s2data['wrd']}
				]
			},
		],
	}
	sheet = gsheet.spreadsheets().create(body=data).execute()
	if 'spreadsheetId' not in sheet:
		return False
	id = sheet['spreadsheetId']
	# format the spreadsheet
	fmt = {
		'requests': [
		{'repeatCell': {
			'range': {
				'sheetId': 0, 'startRowIndex': 1,
				'startColumnIndex': 5, 'endColumnIndex': 9,
			},
			'cell': {
				'userEnteredFormat': {'numberFormat': {'type': 'NUMBER', 'pattern': '0.00%;0%;0%'}}
			},
			'fields': 'userEnteredFormat.numberFormat'}},
		{'repeatCell': {
			'range': {
				'sheetId': 0, 'startRowIndex': 1,
				'startColumnIndex': 9, 'endColumnIndex': 15,
			},
			'cell': {
				'userEnteredFormat': {'numberFormat': {'type': 'NUMBER', 'pattern': '0.000'}}
			},
			'fields': 'userEnteredFormat.numberFormat'}},
		{'autoResizeDimensions': {'dimensions': {'sheetId': 0,
			'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 15}}},
		{'autoResizeDimensions': {'dimensions': {'sheetId': 1,
			'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 5}}},
		{'autoResizeDimensions': {'dimensions': {'sheetId': 2,
			'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 12}}},
		{'autoResizeDimensions': {'dimensions': {'sheetId': 3,
			'dimension': 'COLUMNS', 'startIndex': 0, 'endIndex': 12}}},
		]
	}
	response = gsheet.spreadsheets().batchUpdate(spreadsheetId=id, body=fmt).execute()
	print('{0} cells updated.'.format(len(response.get('replies'))));

	# move the spreadsheet into its proper folder
	file = gdrive.files().get(fileId=id, fields='parents').execute()
	prevpar = ','.join(file.get('parents'))
	file = gdrive.files().update(fileId=id, addParents=kfid,
		removeParents=prevpar, fields='id, parents').execute()
	print 'spreadsheet id: %s' % id
	return True

def pm_graph_report(indir, remotedir='', urlprefix='', name=''):
	desc = {'host':'', 'mode':'', 'kernel':''}
	testruns = []
	idx, count = 0, len(os.listdir(indir))
	# load up all the test data
	for dir in sorted(os.listdir(indir)):
		idx += 1
		if idx % 10 == 0 or idx == count:
			sys.stdout.write('\rLoading data... %.0f%%' % (100*idx/count))
			sys.stdout.flush()
		if not re.match('suspend-[0-9]*-[0-9]*$', dir) or not os.path.isdir(indir+'/'+dir):
			continue
		# create default entry for crash
		dt = datetime.strptime(dir, 'suspend-%y%m%d-%H%M%S')
		testfiles = {
			'html':'.*.html',
			'dmesg':'.*_dmesg.txt',
			'ftrace':'.*_ftrace.txt',
			'result': 'result.txt',
			'crashlog': 'dmesg-crash.log',
			'sshlog': 'sshtest.log',
		}
		data = {'mode': '', 'host': '', 'kernel': '',
			'time': dt.strftime('%Y/%m/%d %H:%M:%S'), 'result': '',
			'issues': '', 'suspend': 0, 'resume': 0, 'sus_worst': '',
			'sus_worsttime': 0, 'res_worst': '', 'res_worsttime': 0,
			'url': dir, 'devlist': dict() }
		# find the files and parse them
		found = dict()
		for file in os.listdir('%s/%s' % (indir, dir)):
			for i in testfiles:
				if re.match(testfiles[i], file):
					found[i] = '%s/%s/%s' % (indir, dir, file)

		if 'html' in found:
			# pass or fail, use html data
			hdata = sg.data_from_html(found['html'], indir)
			if hdata:
				data = hdata
				for key in desc:
					desc[key] = data[key]
		else:
			if len(testruns) == 0:
				print 'ERROR: first test hung'
				return
			for key in desc:
				data[key] = desc[key]
		netlost = False
		if 'sshlog' in found:
			if os.path.getsize(found['sshlog']) < 10:
				netlost = True
			else:
				fp = open(found['sshlog'])
				out = fp.read().strip().split('\n')
				if 'will issue an rtcwake in' in out[-1]:
					netlost = True
		if netlost:
			data['issues'] =  'NETLOST' if not data['issues'] else 'NETLOST '+data['issues']
		if not data['result']:
			if netlost:
				data['result'] = 'hang'
			else:
				data['result'] = 'crash'
		testruns.append(data)
	print ''
	if not desc['host']:
		print 'ERROR: all tests hung, no data'
		return

	# fill out default values based on test desc info
	desc['count'] = '%d' % len(testruns)
	if not remotedir:
		remotedir = os.path.join('pm-graph-test', desc['kernel'], desc['host'])
	if name:
		name = name.format(**desc)
	else:
		name = '%s-x%s-summary' % (desc['mode'], desc['count'])

	# create the summary html
	title = '%s %s %s' % (desc['host'], desc['kernel'], desc['mode'])
	sumfile = os.path.join(indir, 'summary.html')
	devfile = os.path.join(indir, 'summary-devices.html')
	sg.createHTMLSummarySimple(testruns, sumfile, title)
	devall = sg.createHTMLDeviceSummary(testruns, devfile, title)

	# create the summary google sheet
	pid = gdrive_mkdir(remotedir)
	file = createSpreadsheet(testruns, devall, pid, urlprefix, name)
	print 'SUCCESS: spreadsheet created -> %s' % file

def doError(msg, help=False):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit(1)

def printHelp():
	global sysvals

	print('')
	print('Google Sheet Summary Utility')
	print('Usage: googlesheet.py <options> testfolder')
	print('')
	print('Initial Setup:')
	print('  -setup                     Enable access to google drive apis via your account')
	print('  --noauth_local_webserver   Dont use local web browser')
	print('    example: "./googlesheet.py -setup --noauth_local_webserver"')
	print('Options:')
	print('  -remotedir path  The remote path to upload the spreadsheet to (default: root)')
	print('  -urlprefix url   The URL prefix to use to link to each output timeline (default: blank)')
	print('  -name sheetname  The name of the spreadsheet to be created (default: {mode}-x{count}-summary)')
	print('                   Name can include the variables {host}, {mode}, and {count}')
	print('Other commands:')
	print('  -gid gpath       Get the gdrive id for a given file or folder')
	print('')
	return True

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	user = "" if 'USER' not in os.environ else os.environ['USER']
	if len(sys.argv) < 2:
		printHelp()
		sys.exit(1)

	folder = sys.argv[-1]
	remotedir = ''
	urlprefix = ''
	name = ''
	# loop through the command line arguments
	args = iter(sys.argv[1:-1])
	for arg in args:
		if(arg in ['-remotedir', '--remotedir']):
			try:
				val = args.next()
			except:
				doError('No remote dir supplied', True)
			remotedir = val
		elif(arg in ['-urlprefix', '--urlprefix']):
			try:
				val = args.next()
			except:
				doError('No url supplied', True)
			urlprefix = val
		elif(arg in ['-name', '--name']):
			try:
				val = args.next()
			except:
				doError('No name supplied', True)
			name = val
		elif(arg == '-gid'):
			if folder == arg:
				doError('No gpath supplied', True)
			initGoogleAPIs()
			out = gdrive_find(folder)
			if not out:
				out = 'File not found on google drive'
			print out
			sys.exit(0)
		elif(arg == '-setup'):
			setupGoogleAPIs()
			sys.exit(0)
		else:
			doError('Invalid option: %s' % arg, True)

	if folder in ['-h', '--help']:
		printHelp()
		sys.exit(1)
	elif folder == '-gid':
		doError('No gpath supplied', True)
	elif folder[0] == '-':
		doError('Invalid option: %s' % folder, True)

	if not os.path.exists(folder):
		doError('%s does not exist' % folder, False)

	initGoogleAPIs()
	pm_graph_report(folder, remotedir, urlprefix, name)
