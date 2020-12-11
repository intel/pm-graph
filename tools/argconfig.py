#!/usr/bin/env python3

import os
import os.path as op
import argparse
import configparser

def arg_to_path(args, list):
	arglist = vars(args)
	for p in list:
		if p in arglist:
			arglist[p] = op.expanduser(arglist[p])

def args_from_config(parser, args, file, section):
	booltrue = ['enable', 'on', 'true', '1']
	boolvalues = ['disable', 'off', 'false', '0'] + booltrue

	if not op.exists(file):
		return 'config file not found (%s)' % file
	Config, cfg = configparser.ConfigParser(), dict()
	Config.read(file)
	if section not in Config.sections():
		return 'section "%s" not found in config' % section
	for opt in Config.options(section):
		cfg[opt] = Config.get(section, opt)

	arglist = vars(args)
	for key in arglist:
		val = arglist[key]
		if key not in cfg:
			continue
		if isinstance(val, bool):
			if cfg[key].lower() not in boolvalues:
				return '%s -> %s: "%s" is not bool' % (file, key, cfg[key])
			if cfg[key].lower() in booltrue:
				arglist[key] = True
			else:
				arglist[key] = False
		elif isinstance(val, int):
			try:
				arglist[key] = int(cfg[key])
			except:
				return '%s -> %s: "%s" is not int' % (file, key, cfg[key])
		elif isinstance(val, float):
			try:
				arglist[key] = float(cfg[key])
			except:
				return '%s -> %s: "%s" is not float' % (file, key, cfg[key])
		elif isinstance(val, str):
			arglist[key] = cfg[key]

	return ''
