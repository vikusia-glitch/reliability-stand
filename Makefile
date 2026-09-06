# Тонкая обёртка над stand.py — тот работает и в Windows, где make нет.
PY ?= python3

.PHONY: help up down logs test test-docker load load-docker break break-latency heal status check-rules doctor

help:
	@$(PY) stand.py --help

up:            ; $(PY) stand.py up
down:          ; $(PY) stand.py down
logs:          ; $(PY) stand.py logs
doctor:        ; $(PY) stand.py doctor
test:          ; $(PY) stand.py test
test-docker:   ; $(PY) stand.py test --docker
load:          ; $(PY) stand.py load --rps 20 --duration 600
load-docker:   ; $(PY) stand.py load --docker --rps 20 --duration 600
break:         ; $(PY) stand.py break --error-rate 0.10
break-latency: ; $(PY) stand.py break --error-rate 0 --latency-ms 400
heal:          ; $(PY) stand.py heal
status:        ; $(PY) stand.py status
check-rules:   ; $(PY) stand.py check-rules
