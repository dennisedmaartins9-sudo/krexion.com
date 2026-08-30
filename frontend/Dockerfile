# ===============================================================
#  TrackMaster - Frontend Dockerfile (multi-stage)
#  Stage 1: build React app with yarn
#  Stage 2: serve with nginx + proxy /api to backend
# ===============================================================

# ---- Stage 1: build ----
FROM node:20-alpine AS builder

ARG REACT_APP_BACKEND_URL=""
ARG KREXION_VERSION="0.0.0"
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL \
    DISABLE_ESLINT_PLUGIN=true \
    GENERATE_SOURCEMAP=false \
    CI=false \
    KREXION_VERSION=$KREXION_VERSION \
    NODE_OPTIONS=--max-old-space-size=4096

WORKDIR /app

# Copy package files. yarn.lock is optional — use wildcard so the
# COPY step works whether the lockfile exists or not.
COPY package.json package-lock.json* yarn.lock* ./

# Use yarn.lock when present (frozen), else install fresh (will
# generate yarn.lock inside the image).
RUN if [ -f yarn.lock ]; then \
        yarn install --frozen-lockfile --ignore-engines --network-timeout 600000; \
    else \
        yarn install --ignore-engines --network-timeout 600000; \
    fi

# Copy sources and build
COPY . .
RUN yarn build

# Stamp build-version.json — native UI sync + cloud version checks rely on this.
RUN set -e; \
    VER="$(echo "$KREXION_VERSION" | tr -d ' \r\nvV')"; \
    MAIN="$(ls /app/build/static/js/main.*.js 2>/dev/null | head -1)"; \
    test -n "$MAIN"; \
    grep -q "Krexion Browser Profiles" "$MAIN"; \
    printf '{"version":"%s","built_at":"%s","main_js":"%s","marker":"krexion-browser-profiles-v1"}\n' \
      "$VER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$MAIN")" \
      > /app/build/build-version.json

# ---- Stage 2: nginx ----
FROM nginx:1.27-alpine

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
