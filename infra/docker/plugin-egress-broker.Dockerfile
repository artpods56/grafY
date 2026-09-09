FROM python:3.14.0-slim-trixie@sha256:0aecac02dc3d4c5dbb024b753af084cafe41f5416e02193f1ce345d671ec966e

LABEL io.grafy.plugin.egress-broker.policy-config-version="2"

COPY apps/plugin-egress-broker/src/grafy_plugin_egress_broker.py \
    /opt/grafy/bin/grafy-plugin-egress-broker

RUN chmod 0555 /opt/grafy/bin/grafy-plugin-egress-broker

USER 65532:65532
