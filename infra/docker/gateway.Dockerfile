FROM nginx:1.28-alpine

COPY infra/docker/gateway/nginx.conf /etc/nginx/nginx.conf
