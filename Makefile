SERVICE := hems-nilm-gateway
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv install install-prod run service-install service-start service-stop service-restart service-status logs clean

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

install-prod: venv
	$(PIP) install -U pip
	$(PIP) install -e .

run:
	. $(VENV)/bin/activate && export $$(grep -v '^[[:space:]]*#' .env.run | xargs) && \
	$(PY) -m hems_nilm_gateway.gateway.app --artifacts "$$MODEL_ARTIFACT_DIR"

service-install:
	@bash -c 'sudo tee /etc/systemd/system/$(SERVICE).service >/dev/null << "UNIT" \
[Unit] \
Description=HEMS NILM \
After=network-online.target \
Wants=network-online.target \
\
[Service] \
Type=simple \
User=pi \
WorkingDirectory=$(shell pwd) \
EnvironmentFile=$(shell pwd)/.env.run \
ExecStart=$(shell pwd)/$(VENV)/bin/python -m hems_nilm_gateway.gateway.app --artifacts $${MODEL_ARTIFACT_DIR} \
Restart=on-failure \
RestartSec=5 \
\
[Install] \
WantedBy=multi-user.target \
UNIT'
	sudo systemctl daemon-reload
	sudo systemctl enable $(SERVICE)

service-start:
	sudo systemctl start $(SERVICE)

service-stop:
	sudo systemctl stop $(SERVICE)

service-restart:
	sudo systemctl restart $(SERVICE)

service-status:
	systemctl --no-pager status $(SERVICE)

logs:
	journalctl -u $(SERVICE) -f

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache .ruff_cache *.egg-info
