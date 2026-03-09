#!/bin/bash
nmap -sn -n 192.168.32.0/24 2>/dev/null | grep -E "report for|Host is"
