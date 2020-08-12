#!/usr/bin/env python3
#
# Google Sheet Creator
#
# The following additional packages are required beyond the base install:
#
# python2 package requirements:
# sudo apt-get install python-configparser python-requests python-psutil python-httplib2 python-pip
# sudo pip2 install --upgrade google-api-python-client oauth2client
#
# python3 package requirements:
# sudo apt-get install python3-psutil python3-pip
# sudo pip3 install --upgrade google-api-python-client oauth2client
#
# To run -setup without local browser use this command:
#  ./stresstester.py -setup --noauth_local_webserver
#

import os
import sys
import re
import shutil
import time
import fcntl
from subprocess import call, Popen, PIPE
from datetime import datetime
import argparse
import os.path as op
from tools.googleapi import setupGoogleAPIs, initGoogleAPIs,\
	gdrive_command_simple, gdrive_upload, gdrive_sheet

if __name__ == '__main__':

	parser = argparse.ArgumentParser(description='Google Sheet Utility')
	parser.add_argument('-setup', action='store_true',
		help='Setup access to google drive apis via your account')
	parser.add_argument('--noauth_local_webserver', action='store_true',
		help='Run setup without a local web browser (copy a link, paste a verification string)')
	parser.add_argument('-link', metavar='gpath',
		help='Get the URL for a given google drive file/folder')
	parser.add_argument('-list', metavar='gpath',
		help='List the contents of a given google drive folder')
	parser.add_argument('-upload', nargs=2, metavar=('local', 'remote'),
		help='Upload local file to remote gdrive path')
	parser.add_argument('-sheet', nargs=2, metavar=('local', 'remote'),
		help='Upload local csv file to remote googlesheet path')
	args = parser.parse_args()
	if len(sys.argv) < 2:
		parser.print_help()
		sys.exit(1)

	if args.setup:
		sys.exit(setupGoogleAPIs())

	initGoogleAPIs()
	if args.link:
		sys.exit(0 if gdrive_command_simple('link', args.link) else 1)
	elif args.list:
		sys.exit(0 if gdrive_command_simple('list', args.list) else 1)
	elif args.upload:
		sys.exit(0 if gdrive_upload(args.upload[0], args.upload[1]) else 1)
	elif args.sheet:
		sys.exit(0 if gdrive_sheet(args.sheet[0], args.sheet[1]) else 1)
