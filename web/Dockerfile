# Production image for the interviewer/candidate SPA: a Vite build served as
# static files by nginx, which also reverse-proxies the API.
#
# BUILD CONTEXT IS THE REPOSITORY ROOT, not web/ — the policy pages import
# ../../docs/*.md?raw (web/src/legal.ts), so the build needs docs/ as well:
#
#   docker build -f web/Dockerfile -t assessment-web .
#
# Why nginx proxies /api/ instead of the browser calling the API's own origin:
# the refresh cookie is SameSite=lax, and "same site" is decided by origin. One
# origin for both the app and the API is the only arrangement where the session
# survives a reload without loosening the cookie, and it makes CORS_ORIGINS
# irrelevant in this deployment.

# ---- Stage 1: build the static bundle ----
FROM node:24-alpine AS build
WORKDIR /repo

# Install from the lockfile first so a source change doesn't re-resolve npm.
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci

COPY web ./web
COPY docs ./docs

# Vite inlines these at build time — they are baked into the bundle, so a change
# needs a rebuild, not a restart. The default matches the nginx location below.
# Vite's loadEnv copies these from the environment verbatim, and an EMPTY
# string is a value: `import.meta.env.VITE_PRODUCT_NAME ?? 'assess.dev'` in
# branding.ts keeps "" rather than falling back, which renders a blank brand
# name on every sign-in page. So the default lives here, not in an unset var.
#
# VITE_SOURCE_COMMIT is the AGPL §13 half: the app offers its users the source
# of the version they are talking to, which means the sha that was built, not
# whatever the branch points at today. Empty in a local build (there is nothing
# to link to) — the UI then falls back to the repository root. DEPLOY.md §2 has
# the compose spelling; a direct `docker build` passes
# `--build-arg VITE_SOURCE_COMMIT=$(git rev-parse HEAD)`.
ARG VITE_API_BASE_URL=/api
ARG VITE_PRODUCT_NAME=assess.dev
ARG VITE_SOURCE_URL=https://github.com/deepakmdk16/assessment-platform
ARG VITE_SOURCE_COMMIT=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_PRODUCT_NAME=$VITE_PRODUCT_NAME \
    VITE_SOURCE_URL=$VITE_SOURCE_URL \
    VITE_SOURCE_COMMIT=$VITE_SOURCE_COMMIT
RUN cd web && npm run build

# ---- Stage 2: serve ----
FROM nginx:1.27-alpine
# The image's entrypoint renders /etc/nginx/templates/*.template through
# envsubst at start-up, substituting only ${NAME} forms it finds in the
# environment — nginx's own $variables are left alone. That is what lets
# TRUSTED_PROXY_CIDR be set per deployment without rebuilding the image.
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY web/nginx-security-headers.conf /etc/nginx/snippets/security-headers.conf
# Runs before nginx starts, alongside the image's own 20-envsubst step.
COPY --chmod=0755 web/docker-entrypoint.d/30-security-txt.sh /docker-entrypoint.d/
COPY --from=build /repo/web/dist /usr/share/nginx/html

# Trust nobody to declare the client's address; nginx is the edge by default.
ENV TRUSTED_PROXY_CIDR=127.0.0.1
# Empty, not unset: envsubst only substitutes ${NAME} forms that exist in the
# environment, so an unset HSTS_HEADER would reach nginx as a literal
# ${HSTS_HEADER} and be rejected as an unknown variable at boot. Empty means the
# header is simply not added. See docs/DEPLOY.md -> Put TLS in front.
ENV HSTS_HEADER=

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "--spider", "-q", "http://127.0.0.1/index.html"]
