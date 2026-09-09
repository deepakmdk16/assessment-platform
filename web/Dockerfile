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
ARG VITE_API_BASE_URL=/api
ARG VITE_PRODUCT_NAME
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_PRODUCT_NAME=$VITE_PRODUCT_NAME
RUN cd web && npm run build

# ---- Stage 2: serve ----
FROM nginx:1.27-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/web/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "--spider", "-q", "http://127.0.0.1/index.html"]
