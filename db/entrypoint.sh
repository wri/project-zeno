#!/bin/bash
./init-multiple-dbs.sh && \
alembic upgrade head
