#!/usr/bin/python

#
#    Create html directory listing for private files
#    Copyright (C) 2015 Todd Brandt <todd.e.brandt@intel.com>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import sys
import os
import shutil
import string
import re
from datetime import datetime, timedelta
import time
import urllib

def getFileList(dir):
	ignore = ['.git', 'js', 'css', 'index.html', 'webfiles.py']
	files = []
	dirs = []
	html = '<h2>AnalyzeSuspend Timelines</h2>'
	for filename in sorted(os.listdir(dir)):
		if filename in ignore:
			continue
		file = os.path.join(dir, filename)
		if os.path.isfile(file):
			files.append(filename)
		elif os.path.isdir(file):
			dirs.append(filename)
	if len(dirs) > 0:
		html += '<h3>Directories</h3><ul>\n'
		for d in dirs:
			html += '<li><a href="%s">%s</a></li>\n' % (d, d)
			getFileList(os.path.join(dir, d))
		html += '</ul>\n'
	if len(files) > 0:
		html += '<h3>Files</h3><ul>\n'
		for f in files:
			html += '<li><a href="%s">%s</a></li>\n' % (f, f)
		html += '</ul>\n'
	hf = open(os.path.join(dir, 'index.html'), 'w')
	hf.write(html)
	hf.close()

# Function: printHelp
# Description:
#	 print out the help text
def printHelp():
	print('')
	print('WebFiles')
	print('Usage: webfiles.py')
	print('')
	print('Description:')
	print('   Scans the current path and creates an html dir listing')
	print('Options:')
	print('   -h             Print this help text')
	print('')
	return True

# Function: doError
# Description:
#    generic error function for catastrphic failures
# Arguments:
#    msg: the error message to print
#    help: True if printHelp should be called after, False otherwise
def doError(msg, help=False):
	if(help == True):
		printHelp()
	print('ERROR: %s\n') % msg
	sys.exit()

# ----------------- MAIN --------------------
# exec start (skipped if script is loaded as library)
if __name__ == '__main__':

	# loop through the command line arguments
	args = iter(sys.argv[1:])
	for arg in args:
		if(arg == '-h'):
			printHelp()
			sys.exit()
		else:
			doError('Invalid argument: '+arg, True)

	getFileList('.')
