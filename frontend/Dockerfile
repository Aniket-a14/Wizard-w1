# Frontend image.
#
# The runner stage previously copied the whole of `node_modules` out of the
# builder, which meant shipping every build-time dependency -- typescript,
# eslint, tailwind, the Next compiler -- into the production image to serve a
# handful of prerendered routes.
#
# `output: "standalone"` in next.config.ts makes Next trace which files the
# server actually loads at runtime and emit exactly those, so only that is
# copied here.
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

RUN npm run build

# Production image.
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The standalone bundle carries its own minimal node_modules and a server.js.
# `static` and `public` are not traced into it -- Next expects them to be placed
# alongside, and their absence shows up as unstyled pages rather than a crash.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Runs unprivileged: unlike the backend, nothing here needs the Docker socket.
USER node

EXPOSE 3000

CMD ["node", "server.js"]
