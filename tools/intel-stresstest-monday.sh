#!/bin/sh

LOG=`date "+/home/sleepgraph/stresslogs/%y%m%d-%H%M%S-stressreport.txt"`

intel-stresstest report > $LOG 2>&1
