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
import httplib2
try:
	import apiclient.discovery as discovery
	import oauth2client
except:
	print 'Missing libraries, please run this command:'
	print 'sudo pip install --upgrade google-api-python-client oauth2client'
	sys.exit(1)

gdrive = 0
gsheet = 0

def setupGoogleAPIs():
	global gsheet, gdrive

	print '\nSetup involves creating a "credentials.json" file with your account credentials.'
	print 'This requires that you enable access to the google sheets and drive apis for your account.\n'
	SCOPES = 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
	store = oauth2client.file.Storage(sg.sysvals.configFile('credentials.json'))
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
	store = oauth2client.file.Storage(sg.sysvals.configFile('credentials.json'))
	creds = store.get()
	if not creds or creds.invalid:
		print 'ERROR: failed to get google api credentials (please run -setup)'
		sys.exit()
	gdrive = discovery.build('drive', 'v3', http=creds.authorize(httplib2.Http()))
	gsheet = discovery.build('sheets', 'v4', http=creds.authorize(httplib2.Http()))

def gdrive_mkdir(dir=''):
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
						'textFormat': { 'foregroundColor': { 'red': 0.8 } }
					}
				}
			},
			'index': 0
		}
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


def createSpreadsheet(testruns, folder, urlhost, title):
	global gsheet, gdrive

	# remove any duplicate spreadsheets
	query = 'trashed = false and \'%s\' in parents and name = \'%s\'' % (folder, title)
	results = gdrive.files().list(q=query).execute()
	items = results.get('files', [])
	for item in items:
		print 'deleting duplicate - %s (%s)' % (item['name'], item['id'])
		try:
			gdrive.files().delete(fileId=item['id']).execute()
		except errors.HttpError, error:
			doError('gdrive api error on delete file')

	# create the headers row
	headers = ['#','Mode','Host','Kernel','Time','Result','Issues','Suspend',
		'Resume','Worst Suspend Device','SD Time','Worst Resume Device','RD Time',
		'Comments','Timeline']
	headrow = []
	for name in headers:
		headrow.append({
			'userEnteredValue':{'stringValue':name},
			'userEnteredFormat':{
				'textFormat': {'bold': True},
				'horizontalAlignment':'CENTER',
				'borders':{'bottom':{'style':'SOLID'}},
			},
		})

	# assemble the entire spreadsheet into testdata
	i = 1
	possible_results = ['pass', 'fail', 'hang', 'crash']
	desc = {'summary': os.path.join(urlhost, 'summary.html')}
	for key in possible_results:
		desc[key] = 0
	testdata = [{'values':headrow}]
	for test in sorted(testruns, key=lambda v:(v['mode'], v['host'], v['kernel'], v['time'])):
		for key in ['host', 'mode', 'kernel']:
			if key not in desc:
				desc[key] = test[key]
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
	for key in possible_results:
		val = desc[key]
		perc = 100.0*float(val)/float(total)
		desc[key] = '%d (%.1f%%)' % (val, perc)

	# create the summary page info
	summdata = []
	comments = {
		'total':'total number of tests run',
		'pass':'%s entered successfully' % testruns[0]['mode'],
		'fail':'%s NOT entered (bailout before suspend)' % testruns[0]['mode'],
		'hang':'system unrecoverable (ssh connect timeout)',
		'crash':'sleepgraph failed to finish (from instability after resume or tool failure)',
	}
	for key in ['host', 'mode', 'kernel', 'total', 'pass', 'fail', 'hang', 'crash', 'summary']:
		comment = comments[key] if key in comments else ''
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
				'properties': {
					'sheetId': 0,
					'title': 'Summary',
				},
				'data': [
					{
						'startRow': 0,
						'startColumn': 0,
						'rowData': summdata,
					}
				]
			},
			{
				'properties': {
					'sheetId': 1,
					'title': 'Test Data',
				},
				'data': [
					{
						'startRow': 0,
						'startColumn': 0,
						'rowData': testdata,
					}
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
		if not re.match('suspend-[0-9]*-[0-9]*', dir):
			continue
		# create default entry for crash
		dt = datetime.strptime(dir, 'suspend-%y%m%d-%H%M%S')
		testfiles = {
			'html':'.*.html',
			'dmesg':'.*_dmesg.txt',
			'ftrace':'.*_ftrace.txt',
			'result': 'result.txt',
			'crashlog': 'dmesg-crash.log',
		}
		data = {'mode': '', 'host': '', 'kernel': '',
			'time': dt.strftime('%Y/%m/%d %H:%M:%S'), 'result': 'crash',
			'issues': '', 'suspend': 0, 'resume': 0, 'sus_worst': '',
			'sus_worsttime': 0, 'res_worst': '', 'res_worsttime': 0,
			'url': dir}
		# find the files and parse them
		found = dict()
		for file in os.listdir('%s/%s' % (indir, dir)):
			for i in testfiles:
				if re.match(testfiles[i], file):
					found[i] = dir+'/'+file

		if 'html' in found:
			# pass or fail, use html data
			hdata = sg.data_from_html(indir+'/'+found['html'], indir, True)
			if hdata:
				data = hdata
				for key in desc:
					desc[key] = data[key]
		else:
			# crash or hang, use default data
			if len(testruns) == 0:
				print 'ERROR: first test hung'
				return
			for key in desc:
				data[key] = desc[key]
			if len(found.keys()) == 0:
				data['result'] = 'hang'
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

	title = '%s %s %s' % (desc['host'], desc['kernel'], desc['mode'])
	sumfile = os.path.join(indir, 'summary.html')
	sg.createHTMLSummarySimple(testruns, sumfile, title)
	pid = gdrive_mkdir(remotedir)
	file = createSpreadsheet(testruns, pid, urlprefix, name)
	print 'SUCCESS: spreadsheet created -> %s' % file

def doError(msg, help=False):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit()

def printHelp():
	global sysvals

	print('')
	print('Google Sheet Summary Utility')
	print('Usage: googlesheet.py <options> testfolder')
	print('')
	print('Options:')
	print('  -setup           Enable access to google drive apis via your account')
	print('  -remotedir path  The remote path to upload the spreadsheet to (default: root)')
	print('  -urlprefix url   The URL prefix to use to link to each output timeline (default: blank)')
	print('  -name sheetname  The name of the spreadsheet to be created (default: {mode}-x{count}-summary)')
	print('                   Name can include the variables {host}, {mode}, and {count}')
	print('')
	return True

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':
	user = "" if 'USER' not in os.environ else os.environ['USER']
	if len(sys.argv) < 2:
		printHelp()
		sys.exit()

	folder = sys.argv[-1]
	remotedir = ''
	urlprefix = ''
	name = ''
	# loop through the command line arguments
	args = iter(sys.argv[1:-1])
	for arg in args:
		if(arg == '-remotedir'):
			try:
				val = args.next()
			except:
				doError('No remote dir supplied', True)
			remotedir = val
		elif(arg == '-urlprefix'):
			try:
				val = args.next()
			except:
				doError('No url supplied', True)
			urlprefix = val
		elif(arg == '-name'):
			try:
				val = args.next()
			except:
				doError('No name supplied', True)
			name = val
		elif(arg == '-setup'):
			folder = '-setup'
			break
		else:
			doError('Invalid option: %s' % arg, True)

	if folder == '-setup':
		setupGoogleAPIs()
		sys.exit()

	if not os.path.exists(folder):
		doError('%s does not exist' % folder, False)

	initGoogleAPIs()
	pm_graph_report(folder, remotedir, urlprefix, name)
