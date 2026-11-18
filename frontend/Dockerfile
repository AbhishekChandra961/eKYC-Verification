# syntax=docker/dockerfile:1
# The frontend image (Phase 9): a multi-stage build. Stage 1 builds the static files with Node; stage 2 serves them
# with nginx as a non-root user. Node, npm and node_modules (~420 MB) are not in the final image.
#   docker compose --profile app up -d --build        or:  docker build -t ekyc-frontend frontend
# The API address is not baked in: EKYC_API_URL is written to /config.js at container start (docker/40-ekyc-config.sh).

FROM node:22.23.5-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29.8-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY --chmod=755 docker/40-ekyc-config.sh /docker-entrypoint.d/40-ekyc-config.sh
USER root
RUN chown nginx /usr/share/nginx/html/config.js
USER nginx
ENV EKYC_API_URL=http://localhost:8000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
