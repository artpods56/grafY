ARG BUN_VERSION=1.4.4
FROM oven/bun:${BUN_VERSION}-slim AS dependencies

WORKDIR /app

COPY apps/web/package.json apps/web/bun.lock ./
COPY apps/web/scripts ./scripts
RUN bun ci

FROM dependencies AS builder

WORKDIR /app

COPY apps/web ./

RUN bun --bun run build

FROM oven/bun:${BUN_VERSION}-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=builder --chown=bun:bun /app/public ./public
COPY --from=builder --chown=bun:bun /app/.next/standalone ./
COPY --from=builder --chown=bun:bun /app/.next/static ./.next/static

USER bun

EXPOSE 3000

CMD ["bun", "server.js"]
