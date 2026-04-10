.PHONY: install run test crawl reindex reindex-all update-stale fmt

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

crawl:
	python scripts/manage.py crawl

reindex:
	python scripts/manage.py reindex

reindex-all:
	python scripts/manage.py reindex-all

update-stale:
	python scripts/manage.py reindex
