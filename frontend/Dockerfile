# StudyMind frontend: build the static bundle, then serve it with nginx.
#
# Two stages on purpose. Node is only needed to produce the bundle; shipping
# it would mean a ~400MB image to serve a few hundred kilobytes of static
# files. The final image is nginx plus the build output, around 50MB.
#
# Both base images publish linux/amd64 and linux/arm64, so this builds
# natively on Apple Silicon as well as on an x86 CI runner.

FROM node:22-alpine AS build

WORKDIR /app

# package files first: a source change then rebuilds only the bundle, not
# the whole dependency install.
COPY package.json package-lock.json ./
# `npm ci` rather than `npm install`: installs exactly the lockfile, and
# fails loudly if the lockfile and package.json disagree instead of quietly
# resolving something different from what was tested.
RUN npm ci

COPY . .

# The API base URL is baked in at build time, because Vite inlines
# import.meta.env at compile time - there is no runtime env in a static
# bundle. A deployment pointing at a different backend must therefore
# rebuild, which is why this is a build arg rather than an ENV.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Port 8080 and a non-root user: binding below 1024 needs root, and a static
# file server has no reason to run as one.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
