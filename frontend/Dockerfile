# Standard Next.js standalone-output multi-stage build --
# see https://github.com/vercel/next.js/tree/canary/examples/with-docker

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined into the client JS bundle at build time --
# they must be passed as build args, not just runtime env vars.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
ENV PORT=3000
# Docker auto-sets HOSTNAME to the container ID for every container, and
# Next's standalone server.js does `process.env.HOSTNAME || '0.0.0.0'` --
# without overriding it here, the server binds to that container-ID
# hostname instead of all interfaces, so nothing outside the container
# (including Docker's own port mapping) can reach it.
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
