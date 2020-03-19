#!/usr/bin/python

import os
import sys
import time
import fcntl
import os.path as op

httplib2 = discovery = ofile = oclient = otools = None
gdrive = 0
gsheet = 0
lockfile = '/tmp/googleapi.lock'
gdriveids = dict()

def mutex_lock(wait=1):
	global lockfile
	fp, i, success = None, 0, False
	while i < wait and not success:
		success = True
		try:
			fp = open(lockfile, 'w')
			fcntl.flock(fp, fcntl.LOCK_NB | fcntl.LOCK_EX)
		except:
			success = False
			time.sleep(1)
		i += 1
	if not success:
		print('googleapi could not get a lock')
		sys.exit(1)
	return fp

def mutex_unlock(fp):
	fp.close()
	os.remove(lockfile)

def getfile(file):
	dir = os.path.dirname(os.path.realpath(__file__))
	pdir = os.path.realpath(os.path.join(dir, '..'))
	if os.path.exists(file):
		return file
	for d in [pdir, dir]:
		if os.path.exists(d+'/'+file):
			return d+'/'+file
		elif os.path.exists(d+'/config/'+file):
			return d+'/config/'+file
	return ''

def loadGoogleLibraries():
	global httplib2, discovery, ofile, oclient, otools
	try:
		import httplib2
	except:
		print('Missing libraries, please run this command:')
		print('sudo apt-get install python-httplib2')
		sys.exit(1)
	try:
		import apiclient.discovery as discovery
	except:
		print('Missing libraries, please run this command:')
		print('sudo apt-get install python-pip')
		print('sudo pip install --upgrade google-api-python-client')
		sys.exit(1)
	try:
		from oauth2client import file as ofile
		from oauth2client import client as oclient
		from oauth2client import tools as otools
	except:
		print('Missing libraries, please run this command:')
		print('sudo pip install --upgrade oauth2client')
		sys.exit(1)

def setupGoogleAPIs():
	global gsheet, gdrive

	loadGoogleLibraries()
	print('\nSetup involves creating a "credentials.json" file with your account credentials.')
	print('This requires that you enable access to the google sheets and drive apis for your account.\n')
	SCOPES = 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
	# look for a credentials.json file somewhere in our paths
	cf = getfile('credentials.json')
	if not cf:
		cf = 'credentials.json'
	store = ofile.Storage(cf)
	creds = store.get()
	if not creds or creds.invalid:
		if not os.path.exists('client_secret.json'):
			print('ERROR: you are missing the client_secret.json file\n')
			print('Please add client_secret.json by following these instructions:')
			print('https://developers.google.com/drive/api/v3/quickstart/python.')
			print('Click "ENABLE THE DRIVE API" and select the pm-graph project (create a new one if pm-graph is absent)')
			print('Then rename the downloaded credentials.json file to client_secret.json and re-run -setup\n')
			print('If the pm-graph project is not available, you must also add sheet permissions to your project.')
			print('https://developers.google.com/sheets/api/quickstart/python.')
			print('Click "ENABLE THE GOOGLE SHEETS API" and select your project.')
			print('Then rename the downloaded credentials.json file to client_secret.json and re-run -setup\n')
			return 1
		flow = oclient.flow_from_clientsecrets('client_secret.json', SCOPES)
		# this is required because this call includes all the command line arguments
		print('Please login and allow access to these apis.')
		print('The credentials file will be downloaded automatically on completion.')
		del sys.argv[sys.argv.index('-setup')]
		creds = otools.run_flow(flow, store)
	else:
		print('Your credentials.json file appears valid, please delete it to re-run setup')
	return 0

def initGoogleAPIs(force=False):
	global gsheet, gdrive

	# don't reinit unless forced to
	if not force and gdrive and gsheet:
		return

	loadGoogleLibraries()
	SCOPES = 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
	cf = getfile('credentials.json')
	if not cf:
		print('ERROR: no credentials.json file found (please run -setup)')
		sys.exit(1)
	store = ofile.Storage(cf)
	creds = store.get()
	if not creds or creds.invalid:
		print('ERROR: failed to get google api credentials (please run -setup)')
		sys.exit(1)
	gdrive = google_api_command('initdrive', creds)
	gsheet = google_api_command('initsheet', creds)

def google_api_command(cmd, arg1=None, arg2=None, arg3=None, retry=0):
	global gsheet, gdrive

	try:
		if cmd == 'list':
			res = gdrive.files().list(q=arg1, pageSize=1000).execute()
			if 'nextPageToken' in res:
				print('WARNING: list exceeded max results %s' % arg1)
			return res
		elif cmd == 'get':
			return gdrive.files().get(fileId=arg1, fields='parents').execute()
		elif cmd == 'rename':
			return gdrive.files().update(fileId=arg1, body={'name':arg2}, fields='name').execute()
		elif cmd == 'create':
			return gdrive.files().create(body=arg1, fields='id').execute()
		elif cmd == 'delete':
			return gdrive.files().delete(fileId=arg1).execute()
		elif cmd == 'move':
			file = gdrive.files().get(fileId=arg1, fields='parents').execute()
			oldpar = ','.join(file.get('parents'))
			return gdrive.files().update(fileId=arg1, addParents=arg2, removeParents=oldpar, fields='id, parents').execute()
		elif cmd == 'upload':
			return gdrive.files().create(body=arg1, media_body=arg2, fields='id').execute()
		elif cmd == 'createsheet':
			return gsheet.spreadsheets().create(body=arg1).execute()
		elif cmd == 'formatsheet':
			return gsheet.spreadsheets().batchUpdate(spreadsheetId=arg1, body=arg2).execute()
		elif cmd == 'initdrive':
			return discovery.build('drive', 'v3', http=arg1.authorize(httplib2.Http()))
		elif cmd == 'initsheet':
			return discovery.build('sheets', 'v4', http=arg1.authorize(httplib2.Http()))
	except Exception as e:
		if retry >= 10:
			print('ERROR: %s\n' % str(e))
			sys.exit(1)
		if 'User Rate Limit Exceeded' in str(e):
			p, g = os.getpid(), os.getpgrp()
			d = (p - g) % 10 if p != g else 1
			d = 10 if d == 0 else d
			print('RETRYING %s: Rate Limit Exceeded (GID %d, PID %d, WAIT %d sec)' % (cmd, g, p, d))
			time.sleep(d)
		else:
			print('RETRYING %s: %s' % (cmd, str(e)))
			time.sleep(1)
		return google_api_command(cmd, arg1, arg2, arg3, retry+1)
	return False

def gdrive_find(gpath):
	global gdriveids
	# cache the whole file path
	if gpath in gdriveids and gdriveids[gpath]:
		return gdriveids[gpath]
	dir, file = os.path.dirname(gpath), os.path.basename(gpath)
	if dir in ['.', '/']:
		dir = ''
	# cache the dir
	if dir in gdriveids and gdriveids[dir]:
		pid = gdriveids[dir]
	else:
		pid = gdrive_mkdir(dir, readonly=True)
	if not pid:
		return ''
	if not file or file == '.':
		gdriveids[gpath] = pid
		return pid
	query = 'trashed = false and \'%s\' in parents and name = \'%s\'' % (pid, file)
	results = google_api_command('list', query)
	out = results.get('files', [])
	if len(out) > 0 and 'id' in out[0]:
		gdriveids[gpath] = out[0]['id']
		return out[0]['id']
	return ''

def gdrive_mkdir(dir='', readonly=False):
	global gdriveids
	fmime, pid, cpath = 'application/vnd.google-apps.folder', 'root', ''
	if not dir:
		return pid
	if not readonly:
		lock = mutex_lock(60)
	for subdir in dir.split('/'):
		cpath = op.join(cpath, subdir) if cpath else subdir
		if cpath in gdriveids and gdriveids[cpath]:
			pid = gdriveids[cpath]
			continue
		# get a list of folders in this subdir
		query = 'trashed = false and mimeType = \'%s\' and \'%s\' in parents' % (fmime, pid)
		results = google_api_command('list', query)
		id = ''
		for item in results.get('files', []):
			if item['name'] == subdir:
				id = item['id']
				break
		# id this subdir exists, move on
		if id:
			pid = id
			gdriveids[cpath] = id
			continue
		# create the subdir
		if readonly:
			return ''
		else:
			metadata = {'name': subdir, 'mimeType': fmime, 'parents': [pid]}
			file = google_api_command('create', metadata)
			pid = file.get('id')
			gdriveids[cpath] = pid
	if not readonly:
		mutex_unlock(lock)
	return pid

def gdrive_get(folder, name):
	query = 'trashed = false and \'%s\' in parents and name = \'%s\'' % (folder, name)
	results = google_api_command('list', query)
	return results.get('files', [])

def gdrive_delete(folder, name):
	global gdriveids
	for item in gdrive_get(folder, name):
		print('deleting duplicate - %s (%s)' % (item['name'], item['id']))
		google_api_command('delete', item['id'])
	gpath = os.path.join(folder, name)
	del gdriveids[gpath]

def gdrive_backup(folder, name):
	global gdriveids
	gpath = os.path.join(folder, name)
	fid = gdrive_find(folder)
	id = gdrive_find(gpath)
	if not id or not fid:
		return False
	bfid = gdrive_mkdir(os.path.join(folder, 'old'))
	i, append = 1, '.bak'
	while len(gdrive_get(bfid, name+append)) > 0:
		append = '.bak%d' % i
		i += 1
	print('moving duplicate - %s -> old/%s%s' % (name, name, append))
	google_api_command('rename', id, name+append)
	file = google_api_command('move', id, bfid)
	del gdriveids[gpath]
	return True

if __name__ == '__main__':

	initGoogleAPIs()
