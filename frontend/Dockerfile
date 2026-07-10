FROM node:22-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
# Defaults for docker-compose (no BACKEND_URL/PORT set there); Cloud Run overrides
# both. nginx:alpine's own entrypoint envsubst's the template below into
# /etc/nginx/conf.d/default.conf at container start, since neither value is known
# until the container actually runs.
ENV PORT=80
ENV BACKEND_URL=http://backend:8000
COPY --from=build /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
