FROM mcr.microsoft.com/playwright:v1.63.0-noble
WORKDIR /work
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund && npm cache clean --force
COPY . .
RUN npm run check
ENTRYPOINT ["node", "run.mjs"]
