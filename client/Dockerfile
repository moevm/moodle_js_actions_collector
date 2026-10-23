FROM node:22-bookworm-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund \
      --maxsockets=1 --loglevel=verbose \
    || { status=$?; tail -n 150 /root/.npm/_logs/*debug*.log; exit "$status"; }
COPY . .
RUN npm run build
FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist /usr/share/nginx/html/app
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
