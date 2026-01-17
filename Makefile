# Note: These targets assume access to the local LAN registry at registry.plsdontspam.me.

IMAGE = registry.plsdontspam.me/whoami
TAG = latest

.PHONY: build push run_homelab run_local

build:
	docker build -t $(IMAGE):$(TAG) .

push:
	docker push $(IMAGE)

run_homelab: # 5000 ocupied
	docker run --network proxynet -p 5001:5000 $(IMAGE)

run_local:
	FLASK_APP=app.py python -m flask run
