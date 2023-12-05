# SPDX-License-Identifier: GPL-2.0
PREFIX		?= /usr
DESTDIR		?=

all:
	@echo "Nothing to build"

install : uninstall
	install -d  $(DESTDIR)$(PREFIX)/lib/pm-graph
	install sleepgraph.py $(DESTDIR)$(PREFIX)/lib/pm-graph
	install bootgraph.py $(DESTDIR)$(PREFIX)/lib/pm-graph
	install tools/netfix.py $(DESTDIR)$(PREFIX)/lib/pm-graph
	install lib/argconfig.py $(DESTDIR)$(PREFIX)/lib/pm-graph
	install -d  $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/cgskip.txt $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/freeze-callgraph.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/freeze.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/freeze-dev.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/standby-callgraph.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/standby.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/standby-dev.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/suspend-callgraph.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/suspend.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/suspend-dev.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -m 644 config/suspend-x2-proc.cfg $(DESTDIR)$(PREFIX)/lib/pm-graph/config
	install -d  $(DESTDIR)$(PREFIX)/share/pm-graph

	install -d  $(DESTDIR)$(PREFIX)/bin
	ln -s ../lib/pm-graph/bootgraph.py $(DESTDIR)$(PREFIX)/bin/bootgraph
	ln -s ../lib/pm-graph/sleepgraph.py $(DESTDIR)$(PREFIX)/bin/sleepgraph
	ln -s ../lib/pm-graph/netfix.py $(DESTDIR)$(PREFIX)/bin/netfix
	$(DESTDIR)$(PREFIX)/bin/netfix defconfig > $(DESTDIR)$(PREFIX)/share/pm-graph/netfix.cfg

	install -d  $(DESTDIR)$(PREFIX)/share/man/man8
	install bootgraph.8 $(DESTDIR)$(PREFIX)/share/man/man8
	install sleepgraph.8 $(DESTDIR)$(PREFIX)/share/man/man8

uninstall :
	rm -f $(DESTDIR)$(PREFIX)/share/man/man8/bootgraph.8
	rm -f $(DESTDIR)$(PREFIX)/share/man/man8/sleepgraph.8

	rm -f $(DESTDIR)$(PREFIX)/bin/bootgraph
	rm -f $(DESTDIR)$(PREFIX)/bin/sleepgraph
	rm -f $(DESTDIR)$(PREFIX)/bin/netfix

	rm -f $(DESTDIR)$(PREFIX)/lib/pm-graph/config/*
	if [ -d $(DESTDIR)$(PREFIX)/lib/pm-graph/config ] ; then \
		rmdir $(DESTDIR)$(PREFIX)/lib/pm-graph/config; \
	fi;
	rm -f $(DESTDIR)$(PREFIX)/lib/pm-graph/__pycache__/*
	if [ -d $(DESTDIR)$(PREFIX)/lib/pm-graph/__pycache__ ] ; then \
		rmdir $(DESTDIR)$(PREFIX)/lib/pm-graph/__pycache__; \
	fi;
	rm -f $(DESTDIR)$(PREFIX)/lib/pm-graph/*
	if [ -d $(DESTDIR)$(PREFIX)/lib/pm-graph ] ; then \
		rmdir $(DESTDIR)$(PREFIX)/lib/pm-graph; \
	fi;

hwcheck-install :
	install -d  $(DESTDIR)$(PREFIX)/lib/pm-graph
	rm -f $(DESTDIR)$(PREFIX)/bin/hwcheck
	rm -f $(DESTDIR)$(PREFIX)/lib/pm-graph/hwcheck.py
	install tools/hwcheck.py $(DESTDIR)$(PREFIX)/lib/pm-graph
	install -d  $(DESTDIR)$(PREFIX)/bin
	ln -s ../lib/pm-graph/hwcheck.py $(DESTDIR)$(PREFIX)/bin/hwcheck
	$(DESTDIR)$(PREFIX)/bin/hwcheck cronon

hwcheck-uninstall :
	$(DESTDIR)$(PREFIX)/bin/hwcheck cronoff
	rm -f $(DESTDIR)$(PREFIX)/bin/hwcheck
	rm -f $(DESTDIR)$(PREFIX)/lib/pm-graph/hwcheck.py
