FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && python -m pip install --no-cache-dir pytest==8.4.2 fastapi==0.118.3 httpx==0.28.1
COPY suite.py /opt/ktpm/suite.py
USER 65534:65534
